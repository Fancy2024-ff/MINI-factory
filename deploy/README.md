# 部署：常驻 task worker

worker 启动命令两平台一致：

    python -m core.pipeline.task_worker --worker-id <id>

worker 自带 stale 回收（启动 + 周期，多 worker 经 `queue_maintenance` 维护锁互斥），
无需额外 cron。日志统一写到 `data/runtime/logs/`。建议 2 个 worker 起步，最多 4 个。

## macOS（launchd）

1. 复制 `deploy/launchd/com.minifactory.worker.plist` 到 `~/Library/LaunchAgents/`。
2. 把文件里的 `__PYTHON__` 换成 `which python`（或 venv 里的 `python`）的输出，
   `__PROJECT_ROOT__` 换成项目绝对路径（如 `/Users/you/MINI-factory`）。
3. 起第二个 worker：复制一份改 `Label`（如 `com.minifactory.worker2`）和 `--worker-id`。
4. 加载与启动：

       launchctl load ~/Library/LaunchAgents/com.minifactory.worker.plist
       launchctl list | grep minifactory          # 确认在跑

5. 停止 / 卸载：

       launchctl unload ~/Library/LaunchAgents/com.minifactory.worker.plist

6. 看日志：`tail -f data/runtime/logs/worker-launchd.out.log`

`KeepAlive=true`：进程崩溃 launchd 自动拉起；`RunAtLoad=true`：登录即启动。

## Linux（systemd 模板单元）

1. 把项目放到 `/opt/mini-factory`（或改 service 里的路径）。
2. 复制 `deploy/systemd/minifactory-worker@.service` 到 `/etc/systemd/system/`。
3. 起 2 个 worker：

       sudo systemctl daemon-reload
       sudo systemctl enable --now minifactory-worker@1
       sudo systemctl enable --now minifactory-worker@2

4. 状态 / 日志：

       systemctl status minifactory-worker@1
       journalctl -u minifactory-worker@1 -f

5. 停止：`sudo systemctl stop minifactory-worker@1`

`Restart=always`：进程退出 3 秒后自动重启。需要 4 个 worker 就 `@3 @4`。

## 验证 worker 真在消费

    python -m core.runtime.task_store --summary    # 看 pending 是否被消费
