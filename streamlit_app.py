# Streamlit Cloud Secrets 完整配置
# 在Streamlit Cloud控制台 → Settings → Secrets 中粘贴以下内容

# OpenAI API配置
[openai]
api_key = "sk-your-openai-api-key-here"

# 应用设置
[app_settings]
sheet_url = "https://docs.google.com/spreadsheets/d/1g_xoXrBy8MnG_76nrRAT9eNaMytE5YrCYBUK3q5AE04"
source_sheet = "支援审核订单详情"
target_sheet = "电核订单英文翻译"
monthly_budget = 100          # 每月预算（美元）
max_daily_orders = 500        # 每日最大处理订单数
cost_per_1k_tokens = 0.002    # GPT-3.5-turbo价格

# Google服务账号凭据
[google_credentials]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = """-----BEGIN PRIVATE KEY-----
your-private-key-content-here-with-newlines-preserved
-----END PRIVATE KEY-----"""
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs/your-service-account%40your-project.iam.gserviceaccount.com"
universe_domain = "googleapis.com"

# 用户访问控制（推荐启用）
[access_control]
enabled = true                    # 设为 true 启用访问控制，false 禁用
team_password = "mstarJOY-2025"   # 团队访问密码，所有用户需要输入此密码才能使用系统

# 可选：多密钥轮换（高级功能）
[api_key_pool]
enabled = false
keys = [
    "sk-key1-for-department-a",
    "sk-key2-for-department-b", 
    "sk-key3-backup"
]

# 可选：使用量监控
[monitoring]
enable_usage_tracking = true
alert_threshold = 0.8        # 80%预算时发出警告
max_tokens_per_day = 50000   # 每日token限制
