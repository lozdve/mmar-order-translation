import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import openai
from datetime import datetime
import time
import json
import pandas as pd
from typing import Dict, List, Optional

# 页面配置 - 必须在最开头
st.set_page_config(
    page_title="📋 订单翻译工具",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

class OrderTranslator:
    def __init__(self):
        self.gc = None
        self.spreadsheet = None
        
    def initialize_connections(self, credentials_dict: dict, openai_api_key: str) -> bool:
        """初始化Google Sheets和OpenAI连接"""
        try:
            # 设置OpenAI
            openai.api_key = openai_api_key
            
            # 设置Google Sheets
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            self.gc = gspread.authorize(credentials)
            return True
        except Exception as e:
            st.error(f"连接初始化失败: {e}")
            return False
    
    def connect_spreadsheet(self, sheet_url: str) -> bool:
        """连接到指定的电子表格"""
        try:
            if '/spreadsheets/d/' in sheet_url:
                spreadsheet_id = sheet_url.split('/spreadsheets/d/')[1].split('/')[0]
            else:
                spreadsheet_id = sheet_url
            
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            return True
        except Exception as e:
            st.error(f"无法连接到电子表格: {e}")
            return False
    
    def get_worksheets(self) -> List[str]:
        """获取所有工作表名称"""
        if not self.spreadsheet:
            return []
        return [ws.title for ws in self.spreadsheet.worksheets()]
    
    def translate_text(self, text: str) -> str:
        """翻译文本到英文"""
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
            st.warning(f"翻译失败: {e}")
            return f"[Translation Failed] {text}"
    
    def format_combined_content(self, call_content: str, review_advice: str, need_call: bool = True) -> str:
        """格式化合并的UW指令内容"""
        formatted_text = "═══ THE APPROVAL RESULT SHALL BE PROVIDED AFTER RISK INVESTIGATION.@UW ═══\n"
        
        if need_call:
            # 需要电核的格式（原格式）
            formatted_text += "═══ NEED TO CALL AND CONFIRM THE FOLLOWING QUESTIONS： ═══\n\n"
            
            if call_content and call_content.strip():
                formatted_text += call_content.strip() + "\n"
            else:
                formatted_text += "[No call required content]\n"
            
            formatted_text += "\n"
            formatted_text += "═══ REVIEW ADVICE： ═══\n"
            
            if review_advice and review_advice.strip():
                formatted_text += review_advice.strip()
            else:
                formatted_text += "[No review advice]"
        else:
            # 不需要电核的格式（新格式）
            if call_content and call_content.strip():
                formatted_text += call_content.strip() + "\n"
            else:
                formatted_text += "[No content]\n"
            
            formatted_text += "\n"
            formatted_text += "═══ REVIEW ADVICE： ═══\n"
            
            if review_advice and review_advice.strip():
                formatted_text += review_advice.strip()
            else:
                formatted_text += "[No review advice]"
        
        return formatted_text
    
    def find_columns(self, headers: List[str]) -> Dict[str, int]:
        """智能查找列索引"""
        patterns = {
            'date': ['审核日期', '日期', 'date', '审核时间'],
            'order_id': ['订单编号', '订单号', 'order', 'id', '编号'],
            'need_call': ['是否需要电核', '需要电核', '电核'],
            'review_details': ['审核详情', '详情', 'details'],
            'call_content': ['需要电核的内容', '电核内容'],
            'review_advice': ['信审审核意见', '信审意见', '审核意见']
        }
        
        indices = {}
        for key, pattern_list in patterns.items():
            indices[key] = -1
            for pattern in pattern_list:
                try:
                    idx = headers.index(pattern)
                    indices[key] = idx
                    break
                except ValueError:
                    continue
        
        return indices
    
    def parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串"""
        if not date_str:
            return None
        
        formats = ['%Y/%m/%d', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']
        for fmt in formats:
            try:
                return datetime.strptime(str(date_str).strip(), fmt)
            except ValueError:
                continue
        return None
    
    def process_orders(self, source_sheet: str, target_sheet: str, cutoff_date: datetime) -> Dict:
        """处理订单的主函数"""
        try:
            # 获取源数据
            worksheet = self.spreadsheet.worksheet(source_sheet)
            data = worksheet.get_all_values()
            
            if not data:
                return {"success": False, "message": "源表格没有数据"}
            
            headers = data[0]
            indices = self.find_columns(headers)
            
            # 检查必要列
            required = ['date', 'order_id', 'need_call']
            missing = [k for k in required if indices[k] == -1]
            if missing:
                return {"success": False, "message": f"找不到必要的列: {missing}"}
            
            # 筛选数据 - 现在处理所有订单，不再只筛选需要电核的
            filtered_orders = []
            for i, row in enumerate(data[1:], 1):
                try:
                    if len(row) <= max(v for v in indices.values() if v != -1):
                        continue
                    
                    # 检查日期
                    review_date = self.parse_date(row[indices['date']])
                    if not review_date or review_date < cutoff_date:
                        continue
                    
                    # 现在不筛选电核状态，所有符合日期的订单都处理
                    filtered_orders.append(row)
                    
                except Exception:
                    continue
            
            if not filtered_orders:
                return {"success": False, "message": "没有找到符合日期条件的订单"}
            
            # 创建目标工作表
            try:
                target_ws = self.spreadsheet.worksheet(target_sheet)
                target_ws.clear()
            except gspread.WorksheetNotFound:
                target_ws = self.spreadsheet.add_worksheet(
                    title=target_sheet, 
                    rows=len(filtered_orders) + 10, 
                    cols=5
                )
            
            # 设置表头
            headers = ['Review Date', 'Order ID', 'Review Details', 'UW Instructions', 'Processing Date']
            target_ws.update('A1:E1', [headers])
            
            # 处理订单
            processed_data = []
            today = datetime.now().strftime('%Y-%m-%d')
            total = len(filtered_orders)
            
            progress_bar = st.progress(0)
            status_container = st.empty()
            
            for i, row in enumerate(filtered_orders):
                # 更新进度
                progress = (i + 1) / total
                progress_bar.progress(progress)
                status_container.text(f"正在处理第 {i+1}/{total} 个订单...")
                
                try:
                    # 获取数据
                    review_date = row[indices['date']]
                    order_id = row[indices['order_id']]
                    review_details = row[indices['review_details']] if indices['review_details'] != -1 else ''
                    call_content = row[indices['call_content']] if indices['call_content'] != -1 else ''
                    review_advice = row[indices['review_advice']] if indices['review_advice'] != -1 else ''
                    
                    # 判断是否需要电核
                    need_call_value = str(row[indices['need_call']]).strip()
                    need_call = need_call_value in ['是', 'YES', 'yes', 'Y']
                    
                    # 翻译
                    translated_details = self.translate_text(review_details)
                    time.sleep(0.5)
                    
                    translated_call = self.translate_text(call_content)
                    time.sleep(0.5)
                    
                    translated_advice = self.translate_text(review_advice)
                    time.sleep(0.5)
                    
                    # 根据是否需要电核使用不同格式
                    uw_instructions = self.format_combined_content(
                        translated_call, 
                        translated_advice, 
                        need_call  # 传入是否需要电核的标志
                    )
                    
                    processed_data.append([
                        review_date,
                        order_id,
                        translated_details,
                        uw_instructions,
                        today
                    ])
                    
                except Exception as e:
                    st.warning(f"处理订单 {i+1} 时出错: {e}")
                    continue
            
            # 写入数据
            if processed_data:
                # 分批写入
                batch_size = 20
                for i in range(0, len(processed_data), batch_size):
                    batch = processed_data[i:i+batch_size]
                    start_row = i + 2
                    end_row = start_row + len(batch) - 1
                    target_ws.update(f'A{start_row}:E{end_row}', batch)
                    time.sleep(1)
                
                # 格式化
                target_ws.format('A1:E1', {'textFormat': {'bold': True}})
                target_ws.format('D:D', {'wrapStrategy': 'WRAP'})
            
            return {
                "success": True, 
                "message": f"成功处理 {len(processed_data)} 个订单",
                "count": len(processed_data),
                "target_sheet": target_sheet
            }
            
        except Exception as e:
            return {"success": False, "message": f"处理失败: {str(e)}"}

def main():
    """主函数"""
    # 页面标题
    st.title("📋 支援审核订单翻译工具")
    st.markdown("### 🚀 自动翻译电核订单，生成标准英文格式")
    st.markdown("---")
    
    # 侧边栏配置
    with st.sidebar:
        st.header("⚙️ 配置设置")
        
        # 文件上传区域
        st.subheader("📁 凭据文件")
        credentials_file = st.file_uploader(
            "上传Google服务账号凭据",
            type=['json'],
            help="从Google Cloud Console下载的JSON凭据文件"
        )
        
        # API密钥
        openai_key = st.text_input(
            "🔑 OpenAI API Key",
            type="password",
            help="从OpenAI平台获取的API密钥"
        )
        
        st.markdown("---")
        
        # 表格设置
        st.subheader("📊 表格配置")
        sheet_url = st.text_input(
            "📋 Google Sheets URL",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            help="完整的Google Sheets链接"
        )
        
        cutoff_date = st.date_input(
            "📅 筛选起始日期",
            value=datetime(2025, 6, 20),
            help="处理此日期及以后的所有订单（包括需要和不需要电核的）"
        )
        
        target_sheet_name = st.text_input(
            "📝 目标工作表名称",
            value="电核订单英文翻译",
            help="处理结果将保存到此工作表"
        )
    
    # 主界面内容
    if not all([credentials_file, openai_key, sheet_url]):
        # 显示配置提示
        st.info("👈 请在左侧完成所有配置项后开始使用")
        
        # 使用说明
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            #### 🚀 快速开始
            1. **获取Google凭据**
               - 访问 [Google Cloud Console](https://console.cloud.google.com)
               - 创建服务账号并下载JSON文件
               
            2. **获取OpenAI密钥**
               - 访问 [OpenAI平台](https://platform.openai.com/api-keys)
               - 创建新的API密钥
               
            3. **配置权限**
               - 将Google Sheets分享给服务账号邮箱
               - 设置为"编辑者"权限
               
            4. **开始使用**
               - 选择日期范围，处理所有订单
               - 系统自动根据电核需求使用不同格式
            """)
        
        with col2:
            st.markdown("""
            #### ✨ 功能特点
            - 🔍 **智能筛选**：按日期筛选所有订单
            - 🌐 **AI翻译**：使用GPT进行专业翻译
            - 📋 **智能格式**：根据电核需求使用不同格式
            - 📊 **实时进度**：显示处理进度和状态
            - 🔄 **自动保存**：结果直接保存到新工作表
            """)
        
        # 示例展示
        st.markdown("#### 📋 输出格式预览")
        
        tab1, tab2 = st.tabs(["需要电核的订单", "不需要电核的订单"])
        
        with tab1:
            st.markdown("**需要电核订单的UW Instructions格式：**")
            st.code("""
═══ THE APPROVAL RESULT SHALL BE PROVIDED AFTER RISK INVESTIGATION.@UW ═══
═══ NEED TO CALL AND CONFIRM THE FOLLOWING QUESTIONS： ═══

Customer identity verification required by phone call

═══ REVIEW ADVICE： ═══
Recommend approval with additional guarantee required
            """, language="text")
        
        with tab2:
            st.markdown("**不需要电核订单的UW Instructions格式：**")
            st.code("""
═══ THE APPROVAL RESULT SHALL BE PROVIDED AFTER RISK INVESTIGATION.@UW ═══
QA review has been completed and final approval is granted

═══ REVIEW ADVICE： ═══
Customer qualifications are good, direct approval
            """, language="text")
        
        return
    
    # 主处理逻辑
    st.success("✅ 配置完成！准备开始处理订单")
    
    # 初始化处理器
    translator = OrderTranslator()
    
    # 解析凭据文件
    try:
        credentials_dict = json.loads(credentials_file.read())
        credentials_file.seek(0)  # 重置文件指针
    except Exception as e:
        st.error(f"凭据文件格式错误: {e}")
        return
    
    # 连接测试
    with st.spinner("🔗 正在连接服务..."):
        if not translator.initialize_connections(credentials_dict, openai_key):
            return
        
        if not translator.connect_spreadsheet(sheet_url):
            return
    
    st.success("🎉 连接成功！")
    
    # 获取工作表列表
    worksheets = translator.get_worksheets()
    if not worksheets:
        st.error("无法获取工作表列表")
        return
    
    # 工作表选择
    col1, col2 = st.columns(2)
    
    with col1:
        source_sheet = st.selectbox(
            "📋 选择源工作表",
            worksheets,
            index=worksheets.index('支援审核订单详情') if '支援审核订单详情' in worksheets else 0,
            help="包含原始订单数据的工作表"
        )
    
    with col2:
        st.text_input(
            "📝 目标工作表",
            value=target_sheet_name,
            disabled=True,
            help="处理结果将保存到此工作表"
        )
    
    # 处理按钮
    st.markdown("---")
    
    if st.button("🚀 开始处理订单", type="primary", use_container_width=True):
        st.markdown("### 📊 处理进度")
        
        # 转换日期格式
        cutoff_datetime = datetime.combine(cutoff_date, datetime.min.time())
        
        # 开始处理
        with st.spinner("🔄 正在处理订单..."):
            result = translator.process_orders(
                source_sheet,
                target_sheet_name,
                cutoff_datetime
            )
        
        # 显示结果
        if result["success"]:
            st.balloons()
            
            # 成功信息
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("✅ 处理状态", "成功")
            with col2:
                st.metric("📊 处理数量", f"{result['count']} 个订单")
            with col3:
                st.metric("⏱️ 完成时间", datetime.now().strftime('%H:%M:%S'))
            
            # 结果链接
            st.success(f"🎉 {result['message']}")
            st.markdown(f"""
            ### 📋 处理完成！
            
            **目标工作表**: `{result['target_sheet']}`
            
            [🔗 点击查看结果表格]({sheet_url})
            
            **包含内容**:
            - Review Date（审核日期）
            - Order ID（订单编号）
            - Review Details（审核详情 - 英文翻译）
            - UW Instructions（UW指令 - 根据电核需求自动选择格式）
            - Processing Date（处理日期）
            
            **格式说明**:
            - 需要电核的订单：包含"NEED TO CALL AND CONFIRM"部分
            - 不需要电核的订单：直接显示内容和建议
            """)
            
        else:
            st.error(f"❌ 处理失败: {result['message']}")
            
            # 错误处理建议
            st.markdown("""
            #### 🔧 常见问题解决
            
            1. **找不到列**: 检查源工作表的列名是否正确
            2. **没有符合条件的数据**: 确认日期范围和"是否需要电核"字段
            3. **权限错误**: 确保服务账号有编辑表格的权限
            4. **API错误**: 检查OpenAI API密钥是否有效且有余额
            """)

def show_help():
    """显示帮助信息"""
    st.markdown("""
    #### 📖 详细使用说明
    
    **第一步：准备Google凭据**
    1. 访问 [Google Cloud Console](https://console.cloud.google.com)
    2. 创建新项目或选择现有项目
    3. 启用Google Sheets API和Google Drive API
    4. 创建服务账号，下载JSON凭据文件
    
    **第二步：设置表格权限**
    1. 打开你的Google Sheets
    2. 点击"共享"按钮
    3. 添加服务账号的邮箱地址（在JSON文件中找到client_email）
    4. 设置权限为"编辑者"
    
    **第三步：配置OpenAI**
    1. 访问 [OpenAI平台](https://platform.openai.com)
    2. 创建API密钥
    3. 确保账户有足够余额
    
    **第四步：使用工具**
    1. 上传凭据文件
    2. 输入API密钥
    3. 粘贴表格链接
    4. 选择日期范围
    5. 开始处理
    """)

if __name__ == "__main__":
    # 添加帮助页面
    with st.sidebar:
        st.markdown("---")
        if st.button("📖 详细使用说明"):
            show_help()
    
    main()
