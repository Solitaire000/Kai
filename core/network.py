"""
联网状态检测。

v2 说明：这个类现在只用于 /status 展示的"大致联网情况"参考，
不再被 model_router 用来"一票否决"是否尝试在线模型 —— 原因见
model_router.py 顶部的说明（代理环境下，baidu/aliyun可达性和
openrouter/anthropic等境外服务的可达性经常是相反的，用它来
拦截在线请求会导致误判）。

check_urls 默认换成同时包含境内+境外常见站点，尽量减少"有网但被
误判成无网"的情况；即便判断错了现在也不影响实际的模型调用。
"""
import time
import requests


class NetworkChecker:
    def __init__(self, check_urls, timeout_seconds=3, cache_seconds=30):
        self.check_urls = check_urls
        self.timeout = timeout_seconds
        self.cache_seconds = cache_seconds
        self._last_check_time = 0
        self._last_result = False

    def is_online(self, force=False) -> bool:
        """返回是否联网。结果会缓存 cache_seconds 秒，避免频繁探测拖慢响应。"""
        now = time.time()
        if not force and (now - self._last_check_time) < self.cache_seconds:
            return self._last_result

        online = False
        for url in self.check_urls:
            try:
                resp = requests.head(url, timeout=self.timeout)
                if resp.status_code < 500:
                    online = True
                    break
            except requests.RequestException:
                continue

        self._last_check_time = now
        self._last_result = online
        return online
