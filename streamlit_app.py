import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import openai
from datetime import datetime, timedelta
import time
import json
import base64

# 页面配置
st.set_page_config(
    page_title="📋 订单翻译工具",
    page_icon="📋",
    layout="wide"
)

# 预设配置（可以在这里直接设置）
PRESET_CONFIG = {
    "sheet_url": "https://docs.google.com/spreadsheets/d/1g_xoXrBy8MnG_76nrRAT9eNaMytE5YrCYBUK3q5AE04",
    "source_sheet": "支援审核订单详情",
    "target_sheet": "电核订单英文翻译"
}

# 你可以将Google凭据文件内容转换为base64字符串放在这里
# 使用方法：
# 1. 将JSON文件内容复制
# 2. 在Python中运行：import base64; print(base64.b64encode(json_string.encode()).decode())
# 3. 将结果粘贴到下面
PRESET_CREDENTIALS_B64 = ""  # 管理员在这里设置base64编码的凭据

class SimpleOrderTranslator:
    def __init__(self):
        self.gc = None
        self.spreadsheet = None
        
    def initialize_connections(self, credentials_dict: dict, openai_api_key: str) -> bool:
        try:
            openai.api_key = openai_api_key
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            self.gc = gspread.authorize(credentials)
            return True
        except Exception as e:
            st.error(f"连接失败: {e}")
            return False
    
    def connect_spreadsheet(self, sheet_url: str) -> bool:
        try:
            spreadsheet_id = sheet_url.split('/spreadsheets/d/')[1].split('/')[0]
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            return True
        except Exception as e:
            st.error(f"无法连接表格: {e}")
            return False
    
    def translate_text(self, text: str) -> str:
        if not text or text.strip() == '':
            return ''
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{
                    "role": "user", 
                    "content": f"请将以下中文内容翻译成英文，保持专业术语的准确性，只返回翻译结果：\n\n{text}"
                }],
                max_tokens=2000,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"[Translation Failed] {text}"
    
    def format_uw_instructions(self, call_content: str, review_advice: str, need_call: bool) -> str:
        formatted_text = "═══ THE APPROVAL RESULT SHALL BE PROVIDED AFTER RISK INVESTIGATION.@UW ═══\n"
        
        if need_call:
            formatted_text += "═══ NEED TO CALL AND CONFIRM THE FOLLOWING QUESTIONS： ═══\n\n"
            formatted_text += (call_content.strip() if call_content else "[No call content]") + "\n\n"
        else:
            formatted_text += (call_content.strip() if call_content else "[No content]") + "\n\n"
        
        formatted_text += "═══ REVIEW ADVICE： ═══\n"
        formatted_text += (review_advice.strip() if review_advice else "[No advice]")
        
        return formatted_text
    
    def process_orders(self, cutoff_date: datetime, progress_callback=None):
        try:
            worksheet = self.spreadsheet.worksheet(PRESET_CONFIG["source_sheet"])
            data = worksheet.get_all_values()
            
            if not data:
                return {"success": False, "message": "表格没有数据"}
            
            headers = data[0]
            
            # 简化的列查找
            column_indices = {}
            column_map = {
                'date': '审核日期',
                'order_id': '订单编号',
                'need_call': '是否需要电核',
                'review_details': '审核详情',
                'call_content': '需要电核的内容',
                'review_advice': '信审审核意见'
            }
            
            for key, col_name in column_map.items():
                try:
                    column_indices[key] = headers.index(col_name)
                except ValueError:
                    return {"success": False, "message": f"找不到列: {col_name}"}
            
            # 筛选数据
            filtered_orders = []
            for row in data[1:]:
                try:
                    date_str = row[column_indices['date']]
                    review_date = datetime.strptime(date_str, '%Y/%m/%d')
                    
                    if review_date >= cutoff_date:
                        filtered_orders.append(row)
                except:
                    continue
            
            if not filtered_orders:
                return {"success": False, "message": "没有符合条件的订单"}
            
            # 创建目标表格
            try:
                target_ws = self.spreadsheet.worksheet(PRESET_CONFIG["target_sheet"])
                target_ws.clear()
            except:
                target_ws = self.spreadsheet.add_worksheet(
                    title=PRESET_CONFIG["target_sheet"], 
                    rows=len(filtered_orders) + 10, 
                    cols=5
                )
            
            # 设置表头
            headers = ['Review Date', 'Order ID', 'Review Details', 'UW Instructions', 'Processing Date']
            target_ws.update('A1:E1', [headers])
            
            # 处理数据
            processed_data = []
            today = datetime.now().strftime('%Y-%m-%d')
            
            for i, row in enumerate(filtered_orders):
                if progress_callback:
                    progress_callback(i + 1, len(filtered_orders))
                
                try:
                    review_date = row[column_indices['date']]
                    order_id = row[column_indices['order_id']]
                    review_details = row[column_indices['review_details']]
                    call_content = row[column_indices['call_content']]
                    review_advice = row[column_indices['review_advice']]
                    need_call = row[column_indices['need_call']] in ['是', 'YES']
                    
                    # 翻译
                    translated_details = self.translate_text(review_details)
                    time.sleep(0.5)
                    translated_call = self.translate_text(call_content)
                    time.sleep(0.5)
                    translated_advice = self.translate_text(review_advice)
                    time.sleep(0.5)
                    
                    uw_instructions = self.format_uw_instructions(
                        translated_call, translated_advice, need_call
                    )
                    
                    processed_data.append([
                        review_date, order_id, translated_details, uw_instructions, today
                    ])
                    
                except Exception as e:
                    st.warning(f"处理订单 {i+1} 失败: {e}")
                    continue
            
            # 写入数据
            if processed_data:
                target_ws.update('A2', processed_data)
                target_ws.format('A1:E1', {'textFormat': {'bold': True}})
            
            return {"success": True, "message": f"成功处理 {len(processed_data)} 个订单"}
            
        except Exception as e:
            return {"success": False, "message": f"处理失败: {e}"}

def main():
    st.title("📋 订单翻译工具")
    st.markdown("### ⚡ 团队专用版 - 简化配置")
    
    # 配置区域
    with st.form("config_form"):
        st.subheader("🔧 配置")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Google凭据选项
            use_preset = st.checkbox(
                "使用预设的Google凭据", 
                value=bool(PRESET_CREDENTIALS_B64),
                disabled=not bool(PRESET_CREDENTIALS_B64),
                help="管理员已配置团队凭据" if PRESET_CREDENTIALS_B64 else "管理员未配置预设凭据"
            )
            
            if not use_preset:
                credentials_file = st.file_uploader(
                    "上传Google凭据文件", 
                    type=['json']
                )
        
        with col2:
            # OpenAI API密钥
            openai_key = st.text_input(
                "OpenAI API Key", 
                type="password",
                help="必填项"
            )
        
        # 日期选择
        st.subheader("📅 日期设置")
        
        date_options = {
            "今天": datetime.now().date(),
            "昨天": datetime.now().date() - timedelta(days=1),
            "最近3天": datetime.now().date() - timedelta(days=2),
            "最近一周": datetime.now().date() - timedelta(days=6),
            "从6月20日开始": datetime(2025, 6, 20).date()
        }
        
        selected_option = st.selectbox("选择日期范围", list(date_options.keys()), index=4)
        cutoff_date = date_options[selected_option]
        
        st.info(f"将处理 {cutoff_date} 及以后的订单")
        
        # 处理按钮
        submitted = st.form_submit_button("🚀 开始处理", type="primary", use_container_width=True)
    
    # 处理逻辑
    if submitted:
        if not openai_key:
            st.error("请输入OpenAI API Key")
            return
        
        # 准备凭据
        if use_preset and PRESET_CREDENTIALS_B64:
            try:
                credentials_json = base64.b64decode(PRESET_CREDENTIALS_B64).decode()
                credentials_dict = json.loads(credentials_json)
            except Exception as e:
                st.error(f"预设凭据配置错误: {e}")
                return
        elif not use_preset and credentials_file:
            try:
                credentials_dict = json.loads(credentials_file.read())
            except Exception as e:
                st.error(f"凭据文件错误: {e}")
                return
        else:
            st.error("请选择凭据来源")
            return
        
        # 开始处理
        translator = SimpleOrderTranslator()
        
        with st.spinner("正在连接..."):
            if not translator.initialize_connections(credentials_dict, openai_key):
                return
            if not translator.connect_spreadsheet(PRESET_CONFIG["sheet_url"]):
                return
        
        st.success("连接成功！开始处理订单...")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(current, total):
            progress_bar.progress(current / total)
            status_text.text(f"处理进度: {current}/{total}")
        
        cutoff_datetime = datetime.combine(cutoff_date, datetime.min.time())
        result = translator.process_orders(cutoff_datetime, update_progress)
        
        if result["success"]:
            st.balloons()
            st.success(result["message"])
            st.markdown(f"[📋 查看结果]({PRESET_CONFIG['sheet_url']})")
        else:
            st.error(result["message"])

if __name__ == "__main__":
    main()
