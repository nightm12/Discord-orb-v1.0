# Orb Quest Discord Bot

云端常驻的 Discord bot 项目，可部署到 Railway。管理员使用 `/setchannel` 随时变更通知频道；`/setnotifyrole` 预留并启用可选的角色提醒；`/queststatus` 查看配置。美国地区 Orb Quest 不会发进 Discord 频道，而是写入 Railway 日志。

## 重要说明

Quest 数据来自 [DiscordQuest API](https://discordquest.com/document/)，这是社区维护的**非官方**数据源，不隶属于 Discord。数据可能有延迟、遗漏或字段变化。程序只在数据明确标注美国地区、且没有标注为全球范围时，才把任务当作美国任务；无法确认地区的任务会按普通新任务处理。首次启动会记录已有任务作为基线，不会把全部旧任务刷屏。

bot 无法主动向这个 ChatGPT 对话发送消息。美国任务只记入 Railway 部署日志，之后可增加 Discord 私信或另一个私有频道作为提醒目标。

## Railway 部署

1. 将本文件夹上传到自己的 GitHub 仓库。
2. Railway 新建项目，选择 **Deploy from GitHub Repo** 并连接该仓库。
3. 在 Railway 服务的 Variables 中设置 `DISCORD_TOKEN`。可选设置 `DISCORD_GUILD_IDS` 为服务器 ID（单服务器开发时填入可让斜线指令更快出现）。
4. 在 Railway 添加 Volume，挂载路径设为 `/app/data`。否则重新部署后配置和已通知任务记录可能丢失。
5. 部署完成后在 Discord 使用 `/setchannel` 选择目标频道。

Railway 可能按其当时的套餐和用量计费；长期运行不应假设免费。该 bot 使用持续运行的 worker 进程。

## Discord 应用设置

在 Discord Developer Portal 新建 Application 和 Bot，复制 bot token 到 Railway Variables。OAuth2 URL Generator 中选择 `bot` 与 `applications.commands`，bot 权限至少给 `View Channels`、`Send Messages`、`Embed Links`。生成邀请链接并邀请到服务器。不要把 token 提交到 Git、截图或聊天中；如果泄漏，立即在 Developer Portal 重置。

用户若要被 @，服务器管理员先创建一个自选通知角色并在 Discord 中开放成员自行领取（可用服务器内置的 Channels & Roles/Onboarding 或角色菜单 bot）；然后管理员用 `/setnotifyrole` 选择该角色。当前代码支持管理员设置通知角色，尚未内建自助领取角色菜单。

## 本地运行

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# 在 .env 中填 DISCORD_TOKEN
python bot.py
```

## Commands

- `/setchannel channel:#频道`：管理员设置/更改通知频道
- `/setnotifyrole role:@角色`：管理员设置通知角色；不选择角色则关闭 @
- `/queststatus`：查看当前服务器设置
