# Windows 本地环境准备

这个项目推荐用 Docker Compose 启动完整 MVP，所以 Windows 上至少需要：

- Docker Desktop
- Git
- Node.js LTS，包含 npm
- Python 3.12，可选；Docker 部署时不是必须，但本地调试后端会用到

## 推荐安装方式

用 PowerShell 检查 winget：

```powershell
winget --version
```

安装 Docker Desktop：

```powershell
winget install Docker.DockerDesktop
```

安装 Git：

```powershell
winget install Git.Git
```

安装 Node.js LTS：

```powershell
winget install OpenJS.NodeJS.LTS
```

安装 Python 3.12：

```powershell
winget install Python.Python.3.12
```

安装后重新打开 PowerShell，再检查：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-env.ps1
```

## Windows Store Python Alias

如果检查结果里出现：

```text
[WARN] python points to Windows Store alias
```

说明 `python` 可能只是应用商店入口。可以在 Windows 设置里关闭：

```text
设置 → 应用 → 高级应用设置 → 应用执行别名
```

关闭 `python.exe` 和 `python3.exe` 的应用商店别名，然后重新打开终端。

## 启动项目

环境就绪后：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

访问：

- 前端：http://localhost:5173
- API 文档：http://localhost:8000/api/v1/docs
- n8n：http://localhost:5678
