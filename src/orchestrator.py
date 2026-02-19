#!/usr/bin/env python3
"""
Test Suite Orchestrator GRMP
Orchestrates test execution in Docker containers and combines JUnit XML reports.
"""

import os
import yaml
import docker
import time
from pathlib import Path
from typing import Dict, List, Any
from junitparser import JUnitXml
import warnings

class TestOrchestrator:
    def __init__(self, config_dir: str = None, reports_dir: str = None):
        """Initialize the orchestrator with configuration and reports directories."""
        self.config_dir = Path(config_dir or os.getenv('CONFIG_DIR', '/config'))
        self.reports_dir = Path(reports_dir or '/reports')
        
        self.client = docker.from_env()
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Detect the host path for the reports directory
        self.reports_host_path = self._get_reports_host_path()
        
    def _get_reports_host_path(self) -> str:
        """
        Detect the host path for the reports directory.
        """
        env_path = os.getenv('REPORTS_HOST_PATH')
        if env_path:
            print(f"Using REPORTS_HOST_PATH from environment: {env_path}")
            return env_path
        
        try:
            hostname = os.getenv('HOSTNAME')
            if hostname:
                container = self.client.containers.get(hostname)
                mounts = container.attrs.get('Mounts', [])
                
                for mount in mounts:
                    if mount.get('Destination') == '/reports':
                        host_path = mount.get('Source')
                        print(f"Detected host path from container mounts: {host_path}")
                        return host_path
        except Exception as e:
            print(f"Could not detect host path from container: {e}")
        
        # Fallback: assume we're running locally
        fallback_path = str(self.reports_dir.absolute())
        print(f"Using fallback path: {fallback_path}")
        return fallback_path
        
    def load_config(self, config_file: Path) -> Dict[str, Any]:
        """Load a single YAML configuration file."""
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        with open(config_file, "r") as f:
            config = yaml.safe_load(f)

        print(f"Loaded configuration from {config_file}")
        return config


    def load_all_configs(self) -> Dict[str, Any]:
        """Recursively load all YAML files under config_dir, merge them into one config."""
        yaml_files = sorted(list(self.config_dir.rglob("*.yaml")) + list(self.config_dir.rglob("*.yml")))

        if not yaml_files:
            raise FileNotFoundError(f"No YAML files found under {self.config_dir}")

        combined_config: Dict[str, Any] = {"tests": {}}
        test_name_counts: Dict[str, int] = {}

        for yaml_file in yaml_files:
            # Reuse load_config for loading each file
            config = self.load_config(yaml_file)

            if not config or "tests" not in config:
                continue  # skip files without tests

            for test_name, test_data in config["tests"].items():
                original_name = test_name

                # Handle duplicates
                count = test_name_counts.get(original_name, 0)
                if count > 0:
                    warnings.warn(
                        f"Duplicate test name '{original_name}' found in {yaml_file}. "
                        f"Renaming to '{original_name}-{count + 1}'."
                    )
                    test_name = f"{original_name}-{count + 1}"

                test_name_counts[original_name] = count + 1

                # Ensure 'config' node exists and add source file
                test_data["config"] = test_data.get("config") or {}
                test_data["config"]["source_file"] = str(yaml_file)

                combined_config["tests"][test_name] = test_data

            print(f"Processed tests from {yaml_file}")

        return combined_config
    
    def pull_image(self, image: str) -> None:
        """Pull a Docker image from the registry."""
        print(f"  Pulling image: {image}")
        try:
            self.client.images.pull(image)
            print(f"Successfully pulled {image}")
        except docker.errors.ImageNotFound:
            print(f"  Image not found: {image}, will try to use local image if available")
        except Exception as e:
            print(f"Error pulling image {image}: {e}")
    
    def run_test(self, test_name: str, test_image, test_config: Dict[str, Any]) -> str:
        """Run a single test in a Docker container."""
        image = test_image
        if not image:
            raise ValueError(f"Test '{test_name}' missing required 'image' parameter")
        
        print(f"\n▶ Running test: {test_name}")
        print(f"  Image: {image}")
        
        self.pull_image(image)
        
        # TEST_ prefix separates test parameters from system environment variables
        env_vars = {
            'TS_NAME': test_name,
        }
        
        if test_config:
            for key, value in test_config.items():
                if key == 'source_file':
                    env_vars['SPECIAL_SOURCE_FILE'] = str(value)
                elif key != 'image':
                    env_vars[f'TEST_{key.upper()}'] = str(value)
        
        print(f"  Environment variables: {env_vars}")
        
        volumes = {
            self.reports_host_path: {
                'bind': '/reports',
                'mode': 'rw'
            }
        }
        
        print(f"  Mounting host path: {self.reports_host_path} -> /reports")
        
        try:
            container = self.client.containers.run(
                image=image,
                environment=env_vars,
                volumes=volumes,
                detach=False,
                remove=True,
                network_mode='bridge'
            )
            
            print(f"  Container completed successfully")
            
            report_file = f"{test_name}_report.xml"
            report_path = self.reports_dir / report_file
            
            if report_path.exists():
                print(f"  Report file found: {report_file}")
            else:
                print(f"  Warning: Report file not found at {report_path}")
                print(f"  Checking reports directory contents:")
                try:
                    files = list(self.reports_dir.glob('*.xml'))
                    if files:
                        print(f"    Found files: {[f.name for f in files]}")
                    else:
                        print(f"    No XML files found in {self.reports_dir}")
                except Exception as e:
                    print(f"    Error listing directory: {e}")
            
            return report_file
            
        except docker.errors.ContainerError as e:
            print(f"Container failed with exit code {e.exit_status}")
            print(f"Error: {e.stderr.decode() if e.stderr else 'Unknown error'}")
            raise
        except Exception as e:
            print(f"Error running container: {e}")
            raise
    
    def combine_reports(self, report_files: List[str]) -> None:
        """Combine individual jUnit XML reports into a single report using junitparser."""
        print(f"\n▶ Combining {len(report_files)} reports...")
        
        combined = JUnitXml()
        
        # Read and combine each report
        for report_file in report_files:
            report_path = self.reports_dir / report_file
            
            if not report_path.exists():
                print(f"Warning: Report file not found: {report_file}")
                continue
            
            try:
                xml = JUnitXml.fromfile(str(report_path))
                
                for suite in xml:
                    combined.add_testsuite(suite)
                
                print(f"Merged {report_file}")
                
                # Delete individual reports after merge
                report_path.unlink()
                print(f"Deleted {report_file}")
                
            except Exception as e:
                print(f"Error processing {report_file}: {e}")
        
        combined_report = self.reports_dir / 'combined_report.xml'
        combined.write(str(combined_report), pretty=True)
        
        # Calculate and display summary
        total_tests = combined.tests
        total_failures = combined.failures
        total_skipped = combined.skipped
        total_errors = combined.errors
        total_time = combined.time
        
        print(f"Combined report saved to: {combined_report}")
        print(f"Summary: {total_tests} tests, {total_failures} failures, {total_errors} errors, {total_skipped} skipped, {total_time:.3f}s")
    
    def run(self) -> None:
        """Main orchestrator execution flow."""
        print("=" * 60)
        print("Test Suite Orchestrator - Starting")
        print("=" * 60)
        print(f"Reports directory (container): {self.reports_dir}")
        print(f"Reports directory (host): {self.reports_host_path}")
        print("=" * 60)
        
        try:
            config = self.load_all_configs()
            
            tests = config.get('tests', {})
            if not tests:
                print("No tests found in configuration")
                return
            
            print(f"\nFound {len(tests)} test(s) to execute")
            
            # Run each test and collect report filenames
            report_files = []
            for test_name, test_config in tests.items():
                try:
                    test_image = test_config.get('image')
                    test_config_values = test_config.get('config', {})
                    report_file = self.run_test(test_name, test_image, test_config_values)
                    report_files.append(report_file)
                except Exception as e:
                    print(f"Test '{test_name}' failed: {e}")
            
            # Wait a moment for files to be written
            time.sleep(1)
            
            if report_files:
                self.combine_reports(report_files)
            else:
                print("\n No reports to combine")
            
            print("\n" + "=" * 60)
            print("Test Suite Orchestrator - Completed")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n Orchestrator failed: {e}")
            raise


def main():
    """Entry point for the orchestrator."""
    orchestrator = TestOrchestrator()
    orchestrator.run()

if __name__ == '__main__':
    main()
