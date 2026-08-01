# Same 35-feature PromQL schema used by HelmAndSaas/Agent/agent/metrics_collector.py,
# kept identical so this dataset stays comparable to what the live agent observes.

METRIC_QUERIES = [
    # CPU Metrics (0-4)
    ("cpu_user", 'sum(rate(container_cpu_user_seconds_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m])) * 100'),
    ("cpu_system", 'sum(rate(container_cpu_system_seconds_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m])) * 100'),
    ("cpu_total", 'sum(rate(container_cpu_usage_seconds_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m])) * 100'),
    ("cpu_throttled", 'sum(rate(container_cpu_cfs_throttled_seconds_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("cpu_cfs_periods", 'sum(rate(container_cpu_cfs_periods_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),

    # Memory Metrics (5-9)
    ("mem_rss", 'sum(container_memory_rss{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}) / 1024 / 1024'),
    ("mem_cache", 'sum(container_memory_cache{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}) / 1024 / 1024'),
    ("mem_swap", 'sum(container_memory_swap{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}) / 1024 / 1024'),
    ("mem_failcnt", 'sum(container_memory_failcnt{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}})'),
    ("mem_usage", 'sum(container_memory_usage_bytes{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}) / 1024 / 1024'),

    # Network Rx/Tx Metrics (10-19)
    ("rx_bytes", 'sum(rate(container_network_receive_bytes_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("rx_packets", 'sum(rate(container_network_receive_packets_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("rx_errors", 'sum(rate(container_network_receive_errors_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("rx_drop", 'sum(rate(container_network_receive_packets_dropped_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("tx_bytes", 'sum(rate(container_network_transmit_bytes_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("tx_packets", 'sum(rate(container_network_transmit_packets_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("tx_errors", 'sum(rate(container_network_transmit_errors_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("tx_drop", 'sum(rate(container_network_transmit_packets_dropped_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("net_latency_min", 'min(rate(istio_request_duration_milliseconds_sum{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]))'),
    ("net_latency_avg", 'avg(rate(istio_request_duration_milliseconds_sum{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]) / rate(istio_request_duration_milliseconds_count{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]))'),

    # Disk / Block I/O Metrics (20-24)
    ("io_read_bytes", 'sum(rate(container_fs_reads_bytes_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("io_write_bytes", 'sum(rate(container_fs_writes_bytes_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("io_reads", 'sum(rate(container_fs_reads_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("io_writes", 'sum(rate(container_fs_writes_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
    ("io_service_time", 'sum(rate(container_fs_io_time_seconds_total{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),

    # Application / HTTP Metrics (25-34)
    ("http_req_rate", 'sum(rate(istio_requests_total{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]))'),
    ("http_latency", 'avg(rate(istio_request_duration_milliseconds_sum{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]))'),
    ("http_2xx", 'sum(rate(istio_requests_total{{destination_service_name="{name}",destination_service_namespace="{ns}",response_code=~"2.."}}[1m]))'),
    ("http_4xx", 'sum(rate(istio_requests_total{{destination_service_name="{name}",destination_service_namespace="{ns}",response_code=~"4.."}}[1m]))'),
    ("http_5xx", 'sum(rate(istio_requests_total{{destination_service_name="{name}",destination_service_namespace="{ns}",response_code=~"5.."}}[1m]))'),
    ("active_connections", 'sum(go_goroutines{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}})'),
    ("thread_count", 'sum(process_num_threads{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}})'),
    ("open_fds", 'sum(process_open_fds{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}})'),
    ("goroutines", 'sum(go_threads{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}})'),
    ("gc_duration", 'sum(rate(go_gc_duration_seconds_sum{{pod=~"{name}-[^-]+-[^-]+",namespace="{ns}"}}[1m]))'),
]

FEATURE_NAMES = [name for name, _ in METRIC_QUERIES]

SERVICES = ["carts", "catalogue", "front-end", "orders", "payment", "shipping", "user"]

LABELS = {
    "NORMAL": 0,
    "CPU_HOG": 1,
    "MEMORY_LEAK": 2,
    "NETWORK_LATENCY": 3,
}
LABEL_NAMES = {v: k for k, v in LABELS.items()}
