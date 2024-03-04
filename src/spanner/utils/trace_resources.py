import json
import time
from io import BytesIO
from pathlib import Path
from typing import Dict, Union

from discord.ext import tasks

from .utils import run_blocking

try:
    import psutil
except ImportError:
    psutil = None


class Tracer:
    def __init__(self, bot):
        if not psutil:
            raise RuntimeError("psutil is not installed.")

        buffer_dict = Dict[str, Union[int, float, str, list, Dict[str, Union[int, float, str, list]]]]

        self.bot = bot
        self.process = psutil.Process()
        self.buffer: Dict[str, Union[None, list, float, buffer_dict]] = {
            "test_start": None,
            "test_end": None,
            "CPU": {"process": [], "total": [], "cores": {}},
            "RAM": {"process": [], "total": []},
            "threads": [],
        }

    def start(self):
        self.buffer["test_start"] = time.time()
        self.trace_task.start()

    def stop(self, filepath: Union[str, Path, BytesIO] = ..., pretty: bool = True):
        self.trace_task.stop()
        self.buffer["test_end"] = time.time()

        kwargs = {"indent": 4} if pretty else {}

        if isinstance(filepath, BytesIO):
            filepath.write(json.dumps(self.buffer, **kwargs).encode())
            return

        if filepath is ...:
            filepath = self.bot.home / f"trace-{time.time()}.json"

        with open(filepath, "w+") as f:
            json.dump(self.buffer, f, **kwargs)

    @tasks.loop(seconds=5)
    async def trace_task(self):
        cpu_percent = await run_blocking(self.process.cpu_percent, 1)
        overall_cpu_percent = await run_blocking(psutil.cpu_percent, interval=1, percpu=True)
        ram_info = await run_blocking(self.process.memory_full_info)
        threads = len(await run_blocking(self.process.threads))
        overall_ram = await run_blocking(psutil.virtual_memory)

        self.buffer["CPU"]["process"].append(cpu_percent)
        self.buffer["CPU"]["total"].append(sum(overall_cpu_percent))
        for n, core in enumerate(overall_cpu_percent):
            if self.buffer["CPU"]["cores"].get(str(n)) is None:
                self.buffer["CPU"]["cores"][str(n)] = [core]
            else:
                self.buffer["CPU"]["cores"][str(n)].append(core)

        self.buffer["RAM"]["process"].append(ram_info.uss / 1024**2)  # megabytes
        self.buffer["RAM"]["total"].append(overall_ram.used / 1024**2)  # megabytes
        self.buffer["threads"].append(threads)
