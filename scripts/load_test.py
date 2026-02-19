#!/usr/bin/env python3
"""
Load testing script for rate limiter.
Simulates multiple clients making concurrent requests.
"""
import requests
import time
import threading
import statistics
from collections import defaultdict
from datetime import datetime


class LoadTester:
    def __init__(self, base_url, num_clients=10, requests_per_client=20):
        self.base_url = base_url
        self.num_clients = num_clients
        self.requests_per_client = requests_per_client
        self.results = defaultdict(list)
        self.lock = threading.Lock()
    
    def make_requests(self, client_id):
        """Make requests from a single client."""
        session = requests.Session()
        session.headers.update({'X-API-Key': f'client_{client_id}'})
        
        latencies = []
        status_codes = []
        
        for i in range(self.requests_per_client):
            start = time.time()
            try:
                response = session.get(f'{self.base_url}/api/data')
                latency = (time.time() - start) * 1000  # ms
                
                latencies.append(latency)
                status_codes.append(response.status_code)
                
                # Print progress
                if response.status_code == 200:
                    print(f"✓ Client {client_id} - Request {i+1}: {latency:.2f}ms")
                else:
                    print(f"✗ Client {client_id} - Request {i+1}: {response.status_code}")
                
            except Exception as e:
                print(f"✗ Client {client_id} - Request {i+1}: ERROR - {e}")
                status_codes.append(0)
            
            time.sleep(0.1)  # Small delay between requests
        
        with self.lock:
            self.results[client_id] = {
                'latencies': latencies,
                'status_codes': status_codes
            }
    
    def run(self):
        """Run the load test."""
        print(f"\n{'='*60}")
        print(f"🚀 Starting Load Test")
        print(f"{'='*60}")
        print(f"Clients: {self.num_clients}")
        print(f"Requests per client: {self.requests_per_client}")
        print(f"Total requests: {self.num_clients * self.requests_per_client}")
        print(f"Target: {self.base_url}")
        print(f"{'='*60}\n")
        
        start_time = time.time()
        
        # Create threads for each client
        threads = []
        for client_id in range(self.num_clients):
            thread = threading.Thread(
                target=self.make_requests,
                args=(client_id,)
            )
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        duration = time.time() - start_time
        
        # Analyze results
        self.print_results(duration)
    
    def print_results(self, duration):
        """Print test results and statistics."""
        all_latencies = []
        status_counts = defaultdict(int)
        
        for client_data in self.results.values():
            all_latencies.extend(client_data['latencies'])
            for status in client_data['status_codes']:
                status_counts[status] += 1
        
        print(f"\n{'='*60}")
        print(f"📊 Load Test Results")
        print(f"{'='*60}")
        print(f"\n⏱️  Performance Metrics:")
        print(f"  Total Duration: {duration:.2f}s")
        print(f"  Requests/sec: {len(all_latencies) / duration:.2f}")
        
        if all_latencies:
            print(f"\n📈 Latency Statistics:")
            print(f"  Min: {min(all_latencies):.2f}ms")
            print(f"  Max: {max(all_latencies):.2f}ms")
            print(f"  Mean: {statistics.mean(all_latencies):.2f}ms")
            print(f"  Median: {statistics.median(all_latencies):.2f}ms")
            
            sorted_latencies = sorted(all_latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p99_idx = int(len(sorted_latencies) * 0.99)
            print(f"  P95: {sorted_latencies[p95_idx]:.2f}ms")
            print(f"  P99: {sorted_latencies[p99_idx]:.2f}ms")
        
        print(f"\n📋 Status Code Distribution:")
        total_requests = sum(status_counts.values())
        for status, count in sorted(status_counts.items()):
            percentage = (count / total_requests) * 100
            status_emoji = "✅" if status == 200 else "⚠️" if status == 429 else "❌"
            print(f"  {status_emoji} {status}: {count} ({percentage:.1f}%)")
        
        success_rate = (status_counts[200] / total_requests) * 100
        block_rate = (status_counts[429] / total_requests) * 100
        
        print(f"\n🎯 Summary:")
        print(f"  Success Rate: {success_rate:.1f}%")
        print(f"  Block Rate: {block_rate:.1f}%")
        print(f"  Error Rate: {100 - success_rate - block_rate:.1f}%")
        
        print(f"\n{'='*60}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Load test the rate limiter')
    parser.add_argument('--url', default='http://localhost:5000',
                       help='Base URL of the API gateway')
    parser.add_argument('--clients', type=int, default=5,
                       help='Number of concurrent clients')
    parser.add_argument('--requests', type=int, default=20,
                       help='Requests per client')
    
    args = parser.parse_args()
    
    tester = LoadTester(
        base_url=args.url,
        num_clients=args.clients,
        requests_per_client=args.requests
    )
    
    tester.run()


if __name__ == '__main__':
    main()
