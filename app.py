#!/usr/bin/env python3
"""AirPods 电量日志分析器入口。"""

import argparse
import webbrowser

from airpods.cache import Cache
from airpods.server import create_server, default_db_path


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="AirPods 电量日志分析器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--db", default=None, help="缓存数据库路径")
    parser.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args(argv)

    cache = Cache(args.db or default_db_path())
    server = create_server(
        cache=cache,
        host=args.host,
        port=args.port,
    )
    url = f"http://{args.host}:{args.port}/"

    print(f"AirPods 电量分析器已启动：{url}")
    print("按 Ctrl+C 停止。")

    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - headless environments
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.jobs.shutdown()
        server.server_close()
        cache.close()


if __name__ == "__main__":
    main()
