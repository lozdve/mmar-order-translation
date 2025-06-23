######
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import openai
from datetime import datetime
import time
import json
import io

# 必须在文件开头设置页面配置
st.set_page_config(
    page_title="订单翻译工具",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 主应用代码...
