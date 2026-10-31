# GitHub Copilot 额度监控

一个基于 Streamlit 的 GitHub Copilot 额度和 AI Credits 使用情况监控面板，支持：

- 查看当前 Copilot 订阅计划、账户类型、剩余额度和重置时间（免费版暂时不兼容）
- 按模型查看 AI Credits 使用量
- 保存每日额度与模型用量历史
- 查看本月趋势图和模型明细
- 网络请求失败时使用本地历史数据离线展示
- 第一次使用提供回填本月缺失的历史日期功能

## 在线示例

可以直接访问在线示例体验：

[Copilot 额度监控 · Streamlit](https://app-copilot-monitor-adymgqt4yvi8wh6gvawcc5.streamlit.app/)

在线示例使用 Streamlit Cloud 部署。首次访问时需要输入自己的 GitHub 用户名和 Personal Access Token；项目不会提供或代为收集访问者的 Token。在线示例与本地部署使用相同的登录、额度查询和历史数据展示流程，实际可读取的数据取决于当前 GitHub 账户的 Copilot 权限和 Token 权限。

## 项目结构

```text
.
├── backend/
│   ├── app.py              # Streamlit 入口、登录门禁和页面编排
│   ├── dashboard.py        # 页面布局、图表和交互
│   ├── data_service.py     # 数据获取、缓存和离线降级
│   ├── api_client.py       # GitHub API 客户端
│   ├── core_logic.py       # 配额解析和用量聚合
│   ├── database.py         # Supabase 数据访问
│   ├── authenticate.py     # GitHub 凭证验证
│   └── logger_setup.py     # 全局日志配置
├── requirements.txt
└── 访问令牌.txt             # Token 申请步骤参考
```

## 运行环境

- Python 3.11 或更高版本
- GitHub 账户及 Copilot 使用权限
- Supabase 项目，用于持久化历史数据

## 安装依赖

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如果 PowerShell 禁止执行虚拟环境脚本，也可以直接使用：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 创建 GitHub Personal Access Token

本项目登录时需要 GitHub 用户名和 Personal Access Token。Token 只保存在当前 Streamlit 会话中，不应提交到代码仓库或写入日志。

### 1. 打开 Token 设置

登录 GitHub 后打开：

<https://github.com/settings/personal-access-tokens>

也可以通过以下菜单进入：

`Settings` → `Developer settings` → `Personal access tokens` → `Fine-grained tokens`

### 2. 创建 Token

点击 **Generate new token**。如果 GitHub 要求验证身份，请按页面提示完成验证。

### 3. 填写基本信息

可参考：

- **Token name**：`Copilot-Quota-Monitor`
- **Description**：`Read Copilot billing usage for personal dashboard`
- **Expiration**：设置合理的有效期，过期后需要重新生成
- **Resource owner**：选择拥有 Copilot 订阅和账单数据的个人账户

### 4. 设置 Repository access

本项目读取的是个人账户的 Copilot 额度和账单使用数据，不需要为了该功能开放仓库内容权限。不要授予与项目无关的仓库访问权限。

### 5. 设置 Account permissions

在 **Account permissions** 中，根据 GitHub 当前 Billing REST API 的权限要求，为 **Plan** 选择 **Read-only**。

注意：

- **Plan** 是账户级权限，不是仓库权限。
- 不要把 Plan 与 `Contents`、`Issues` 等仓库权限混淆。
- 如果当前 Token 类型或账户页面没有 Plan 权限，不要随意授予其他高权限；请先查看 GitHub 官方 Billing REST API 的最新要求。
- 始终遵循最小权限原则。

### 6. 生成并保存 Token

点击 **Generate token**。GitHub 通常只在生成时显示完整 Token，请立即复制并安全保存。离开页面后通常无法再次查看原始值。

## 配置 Supabase

应用使用 Supabase 保存每日历史数据。创建 Supabase 项目后，在项目的 SQL Editor 中创建以下两张表：

创建 Supabase 时请注意：

- 选择与使用者所在区域和部署环境相适合的项目区域；项目创建后通常不能直接更换区域。
- 保存好项目 URL 和密钥。项目 URL 可以用于连接配置，但密钥必须保密。
- 生产环境建议使用服务端密钥，并只通过 Streamlit Secrets 配置；不要把密钥写入 Python 文件、README、截图或提交记录。
- `SUPABASE_SERVICE_ROLE_KEY` 具有较高权限，会绕过部分 RLS（Row Level Security）策略。必须避免泄露，不能放在前端代码、浏览器脚本或公开仓库中。
- 如果改用 anon key，必须根据实际用户隔离需求配置 RLS；否则可能无法写入，或造成不同用户之间的数据访问风险。
- 下面的表使用 `(record_date, username)` 和 `(record_date, username, model_name)` 作为联合主键，不能省略，否则 `upsert` 无法按预期去重。
- `record_date` 应使用 `date` 类型，额度字段应使用 `double precision` 或其他能够保存小数的数值类型。
- 执行 SQL 后，请确认两张表已成功创建，并检查表名、列名和联合主键与下面定义完全一致。

```sql
create table if not exists total_daily_usage (
  record_date date not null,
  username text not null,
  included_credits double precision not null default 0,
  used_credits double precision not null default 0,
  remaining_credits double precision not null default 0,
  primary key (record_date, username)
);

create table if not exists model_daily_usage (
  record_date date not null,
  username text not null,
  model_name text not null,
  used_credits double precision not null default 0,
  primary key (record_date, username, model_name)
);
```

如果启用了 RLS，请根据部署方式配置对应策略。使用服务端密钥时仍应严格保护密钥；不要为了排查问题而把数据库设置为完全公开。

在项目根目录创建 `.streamlit/secrets.toml`。该文件已被 `.gitignore` 忽略，不要提交到 Git：

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-supabase-service-role-key"
```

代码也兼容 `SUPABASE_KEY`、`SUPABASE_ANON_KEY` 或 `[supabase]` 配置块，但建议使用服务端密钥并妥善保护。

## 启动应用

在项目根目录运行：

```powershell
.\.venv\Scripts\streamlit.exe run backend\app.py
```

或在已激活虚拟环境后运行：

```powershell
streamlit run backend\app.py
```

浏览器打开 Streamlit 输出的本地地址，输入 GitHub 用户名和 Token 登录。

## 使用说明

### 刷新数据

点击 **刷新数据** 会绕过 15 分钟 API 缓存，重新获取 GitHub 数据，并保存当天快照。

### 回填本月历史数据

点击 **回填本月历史数据** 后，应用会：

1. 查询本月已经保存的日期；
2. 识别从本月 1 日到昨天之间缺失的日期；
3. 只请求这些缺失日期；
4. 跳过已经存在的日期；
5. 将缺失日期的累计用量接续到已有历史数据之后。

因此，如果某天没有打开应用，只会补齐缺失日期，不会重复覆盖已有日期。

## 缓存、离线模式和日志

- GitHub API 数据默认缓存 15 分钟。
- GitHub 请求失败时，如果 Supabase 中存在历史快照，页面会切换到离线模式。
- 日志写入 `backend/app.log`，同时输出到控制台。
- 日志初始化是幂等的，Streamlit 重载不会重复添加日志处理器。
- Token 不应出现在日志、截图、提交记录或公开 issue 中。

## 常见问题

### 提示缺少 Supabase 配置

确认 `.streamlit/secrets.toml` 存在，并至少配置：

```toml
SUPABASE_URL = "..."
SUPABASE_SERVICE_ROLE_KEY = "..."
```

### Token 验证失败

检查用户名是否与 Token 所属账户一致、Token 是否过期，以及账户级 **Plan: Read-only** 权限是否已授予。必要时撤销旧 Token 后按本文步骤重新生成。

### 页面没有当天历史数据

正常流程只在成功获取实时数据后保存当天快照。如果当天没有打开应用，之后点击 **回填本月历史数据** 即可补齐缺失日期。

## 安全提醒

- 不要提交 `.streamlit/secrets.toml`、`.env`、Token、Supabase 密钥或 `backend/app.log`。
- 不要在 issue、截图或聊天记录中粘贴完整 Token。
- Token 泄露后应立即在 GitHub 设置中撤销并重新生成。
- 仅授予项目实际需要的最低权限。
