import asyncio
import logging
from prometheus_api_client import PrometheusConnect
from .config import config

logger = logging.getLogger(__name__)

# List of 35 Prometheus queries mapped to feature vector indices [0..34]
METRIC_QUERIES = [
    # CPU Metrics (0-4)
    ("cpu_user", 'sum(rate(container_cpu_user_seconds_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m])) * 100'),
    ("cpu_system", 'sum(rate(container_cpu_system_seconds_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m])) * 100'),
    ("cpu_total", 'sum(rate(container_cpu_usage_seconds_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m])) * 100'),
    ("cpu_throttled", 'sum(rate(container_cpu_cfs_throttled_seconds_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("cpu_cfs_periods", 'sum(rate(container_cpu_cfs_periods_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    
    # Memory Metrics (5-9)
    ("mem_rss", 'sum(container_memory_rss{{pod=~"{name}-.*",namespace="{ns}"}}) / 1024 / 1024'),
    ("mem_cache", 'sum(container_memory_cache{{pod=~"{name}-.*",namespace="{ns}"}}) / 1024 / 1024'),
    ("mem_swap", 'sum(container_memory_swap{{pod=~"{name}-.*",namespace="{ns}"}}) / 1024 / 1024'),
    ("mem_failcnt", 'sum(container_memory_failcnt{{pod=~"{name}-.*",namespace="{ns}"}})'),
    ("mem_usage", 'sum(container_memory_usage_bytes{{pod=~"{name}-.*",namespace="{ns}"}}) / 1024 / 1024'),

    # Network Rx/Tx Metrics (10-19)
    ("rx_bytes", 'sum(rate(container_network_receive_bytes_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("rx_packets", 'sum(rate(container_network_receive_packets_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("rx_errors", 'sum(rate(container_network_receive_errors_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("rx_drop", 'sum(rate(container_network_receive_packets_dropped_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("tx_bytes", 'sum(rate(container_network_transmit_bytes_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("tx_packets", 'sum(rate(container_network_transmit_packets_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("tx_errors", 'sum(rate(container_network_transmit_errors_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("tx_drop", 'sum(rate(container_network_transmit_packets_dropped_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("net_latency_min", 'min(rate(istio_request_duration_milliseconds_sum{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]))'),
    ("net_latency_avg", 'avg(rate(istio_request_duration_milliseconds_sum{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]) / rate(istio_request_duration_milliseconds_count{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]))'),

    # Disk / Block I/O Metrics (20-24)
    ("io_read_bytes", 'sum(rate(container_fs_reads_bytes_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("io_write_bytes", 'sum(rate(container_fs_writes_bytes_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("io_reads", 'sum(rate(container_fs_reads_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("io_writes", 'sum(rate(container_fs_writes_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),
    ("io_service_time", 'sum(rate(container_fs_io_time_seconds_total{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))'),

    # Application / HTTP Metrics (25-34)
    ("http_req_rate", 'sum(rate(istio_requests_total{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]))'),
    ("http_latency", 'avg(rate(istio_request_duration_milliseconds_sum{{destination_service_name="{name}",destination_service_namespace="{ns}"}}[1m]))'),
    ("http_2xx", 'sum(rate(istio_requests_total{{destination_service_name="{name}",destination_service_namespace="{ns}",response_code=~"2.."}}[1m]))'),
    ("http_4xx", 'sum(rate(istio_requests_total{{destination_service_name="{name}",destination_service_namespace="{ns}",response_code=~"4.."}}[1m]))'),
    ("http_5xx", 'sum(rate(istio_requests_total{{destination_service_name="{name}",destination_service_namespace="{ns}",response_code=~"5.."}}[1m]))'),
    ("active_connections", 'sum(go_goroutines{{pod=~"{name}-.*",namespace="{ns}"}})'),
    ("thread_count", 'sum(process_num_threads{{pod=~"{name}-.*",namespace="{ns}"}})'),
    ("open_fds", 'sum(process_open_fds{{pod=~"{name}-.*",namespace="{ns}"}})'),
    ("goroutines", 'sum(go_threads{{pod=~"{name}-.*",namespace="{ns}"}})'),
    ("gc_duration", 'sum(rate(go_gc_duration_seconds_sum{{pod=~"{name}-.*",namespace="{ns}"}}[1m]))')
]


class MetricsCollector:
    def __init__(self, prometheus_url):
        self.prom = PrometheusConnect(url=prometheus_url, disable_ssl=True)

    async def collect(self, services):
        logger.debug(f"Collecting metrics for {len(services)} services")
        
        tasks = [self._get_service_metrics(svc) for svc in services]
        results = await asyncio.gather(*tasks)
        
        return [r for r in results if r is not None]

    async def _get_service_metrics(self, svc):
        name = svc["name"]
        ns = svc["namespace"]
        
        try:
            metrics_dict = {}
            feature_vector = []

            # Execute 35 PromQL queries in exact index order [0..34]
            for metric_name, query_template in METRIC_QUERIES:
                q = query_template.format(name=name, ns=ns)
                val = self._query_value(q) or 0.0
                metrics_dict[metric_name] = val
                feature_vector.append(val)

            # Standard 5-feature summary metrics for backwards compatibility
            metrics_dict["cpu_usage_percent"] = metrics_dict.get("cpu_total", 0.0)
            metrics_dict["memory_usage_mb"] = metrics_dict.get("mem_usage", 0.0)
            metrics_dict["network_latency_ms"] = metrics_dict.get("net_latency_avg", 0.0)
            metrics_dict["request_rate"] = metrics_dict.get("http_req_rate", 0.0)
            metrics_dict["error_rate"] = metrics_dict.get("http_5xx", 0.0)
            metrics_dict["cpu_trend"] = 0.0
            metrics_dict["memory_trend"] = 0.0

            return {
                "service_name": name,
                "namespace": ns,
                "metrics": metrics_dict,
                "feature_vector": feature_vector  # Exact 35-length array
            }
        except Exception as e:
            logger.error(f"Error collecting metrics for {name}: {e}")
            return None

    def _query_value(self, query):
        try:
            result = self.prom.custom_query(query)
            if result and len(result) > 0:
                return float(result[0]['value'][1])
            return 0.0
        except Exception:
            return 0.0

