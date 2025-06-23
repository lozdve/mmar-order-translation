import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import openai
from datetime import datetime, timedelta
import time
import json

# 页面配置
st.set_page_config(
    page_title="📋 订单翻译工具",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

class OrderTranslator:
    def __init__(self):
        self.gc = None
        self.spreadsheet = None
        self.usage_stats = {"orders_processed": 0, "tokens_used": 0}
        
    def initialize_with_secrets(self) -> bool:
        """使用Streamlit Secrets初始化所有连接"""
        try:
            # 检查OpenAI配置
            if "openai" not in st.secrets:
                st.error("⚠️ 管理员需要配置OpenAI API密钥")
                with st.expander("📖 配置说明"):
                    st.code("""
# 在Streamlit Cloud Secrets中添加：
[openai]
api_key = "sk-your-openai-api-key"
                    """)
                return False
            
            # 检查Google凭据
            if "google_credentials" not in st.secrets:
                st.error("⚠️ 管理员需要配置Google凭据")
                with st.expander("📖 配置说明"):
                    st.code("""
# 在Streamlit Cloud Secrets中添加：
[google_credentials]
type = "service_account"
project_id = "your-project-id"
# ... 其他Google凭据字段
                    """)
                return False
            
            # 设置OpenAI
            openai.api_key = st.secrets["openai"]["api_key"]
            
            # 设置Google Sheets
            credentials_dict = dict(st.secrets["google_credentials"])
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            self.gc = gspread.authorize(credentials)
            
            # 连接表格
            sheet_url = st.secrets.get("app_settings", {}).get("sheet_url", 
                "https://docs.google.com/spreadsheets/d/1g_xoXrBy8MnG_76nrRAT9eNaMytE5YrCYBUK3q5AE04")
            spreadsheet_id = sheet_url.split('/spreadsheets/d/')[1].split('/')[0]
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            
            return True
            
        except Exception as e:
            st.error(f"❌ 初始化失败: {e}")
            
            # 提供详细的错误帮助
            with st.expander("🔧 故障排除"):
                st.markdown("""
                **可能的问题：**
                1. Streamlit Secrets配置不正确
                2. Google服务账号权限不足
                3. OpenAI API密钥无效
                4. Google Sheets未分享给服务账号
                
                **解决步骤：**
                1. 检查Streamlit Cloud → Settings → Secrets配置
                2. 确认Google Sheets已分享给服务账号邮箱
                3. 验证OpenAI API密钥有效且有余额
                """)
            return False
    
    def translate_text(self, text: str) -> str:
        """翻译文本"""
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
            
            # 统计使用量
            if "usage" in response:
                self.usage_stats["tokens_used"] += response["usage"]["total_tokens"]
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            st.warning(f"翻译失败: {e}")
            return f"[Translation Failed] {text}"
    
    def format_uw_instructions(self, call_content: str, review_advice: str, need_call: bool) -> str:
        """格式化UW指令"""
        formatted_text = "═══ THE APPROVAL RESULT SHALL BE PROVIDED AFTER RISK INVESTIGATION.@UW ═══\n"
        
        if need_call:
            formatted_text += "═══ NEED TO CALL AND CONFIRM THE FOLLOWING QUESTIONS： ═══\n\n"
            formatted_text += (call_content.strip() if call_content else "[No call content]") + "\n\n"
        else:
            formatted_text += (call_content.strip() if call_content else "[No content]") + "\n\n"
        
        formatted_text += "═══ REVIEW ADVICE： ═══\n"
        formatted_text += (review_advice.strip() if review_advice else "[No advice]")
        
        return formatted_text
    
    def get_usage_info(self):
        """获取使用统计"""
        settings = st.secrets.get("app_settings", {})
        monthly_budget = settings.get("monthly_budget", 100)
        max_daily_orders = settings.get("max_daily_orders", 500)
        
        # 估算成本
        estimated_cost = (self.usage_stats["tokens_used"] / 1000) * 0.002
        
        return {
            "orders_processed": self.usage_stats["orders_processed"],
            "tokens_used": self.usage_stats["tokens_used"],
            "estimated_cost": estimated_cost,
            "monthly_budget": monthly_budget,
            "max_daily_orders": max_daily_orders
        }
    
    def process_orders(self, cutoff_date: datetime, progress_container=None):
        """处理订单"""
        try:
            # 获取配置
            settings = st.secrets.get("app_settings", {})
            source_sheet_name = settings.get("source_sheet", "支援审核订单详情")
            target_sheet_name = settings.get("target_sheet", "电核订单英文翻译")
            
            # 获取数据
            worksheet = self.spreadsheet.worksheet(source_sheet_name)
            data = worksheet.get_all_values()
            
            if not data:
                return {"success": False, "message": "表格没有数据"}
            
            headers = data[0]
            
            # 查找列索引
            column_map = {
                'date': ['审核日期', '日期'],
                'order_id': ['订单编号', '订单号'],
                'need_call': ['是否需要电核', '需要电核'],
                'review_details': ['审核详情', '详情'],
                'call_content': ['需要电核的内容', '电核内容'],
                'review_advice': ['信审审核意见', '信审意见']
            }
            
            indices = {}
            for key, possible_names in column_map.items():
                indices[key] = -1
                for name in possible_names:
                    try:
                        indices[key] = headers.index(name)
                        break
                    except ValueError:
                        continue
                
                if indices[key] == -1:
                    return {"success": False, "message": f"找不到列: {possible_names[0]}"}
            
            # 筛选数据
            filtered_orders = []
            for row in data[1:]:
                try:
                    if len(row) <= max(indices.values()):
                        continue
                    
                    date_str = row[indices['date']]
                    review_date = None
                    
                    # 尝试多种日期格式
                    for date_format in ['%Y/%m/%d', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                        try:
                            review_date = datetime.strptime(date_str, date_format)
                            break
                        except ValueError:
                            continue
                    
                    if review_date and review_date >= cutoff_date:
                        filtered_orders.append(row)
                        
                except Exception:
                    continue
            
            if not filtered_orders:
                return {"success": False, "message": f"没有找到 {cutoff_date.strftime('%Y-%m-%d')} 及以后的订单"}
            
            # 检查限制
            usage_info = self.get_usage_info()
            if len(filtered_orders) > usage_info["max_daily_orders"]:
                return {
                    "success": False,
                    "message": f"订单数量({len(filtered_orders)})超过每日限制({usage_info['max_daily_orders']})"
                }
            
            # 创建目标工作表
            try:
                target_ws = self.spreadsheet.worksheet(target_sheet_name)
                target_ws.clear()
            except gspread.WorksheetNotFound:
                target_ws = self.spreadsheet.add_worksheet(
                    title=target_sheet_name, 
                    rows=len(filtered_orders) + 10, 
                    cols=5
                )
            
            # 设置表头
            headers_row = ['Review Date', 'Order ID', 'Review Details', 'UW Instructions', 'Processing Date']
            target_ws.update('A1:E1', [headers_row])
            
            # 处理订单
            processed_data = []
            today = datetime.now().strftime('%Y-%m-%d')
            
            for i, row in enumerate(filtered_orders):
                # 更新进度
                if progress_container:
                    progress = (i + 1) / len(filtered_orders)
                    progress_container.progress(progress)
                
                try:
                    review_date = row[indices['date']]
                    order_id = row[indices['order_id']]
                    review_details = row[indices['review_details']]
                    call_content = row[indices['call_content']]
                    review_advice = row[indices['review_advice']]
                    need_call = row[indices['need_call']] in ['是', 'YES', 'yes']
                    
                    # 翻译处理
                    translated_details = self.translate_text(review_details)
                    time.sleep(0.3)
                    
                    translated_call = self.translate_text(call_content)
                    time.sleep(0.3)
                    
                    translated_advice = self.translate_text(review_advice)
                    time.sleep(0.3)
                    
                    # 格式化
                    uw_instructions = self.format_uw_instructions(
                        translated_call, translated_advice, need_call
                    )
                    
                    processed_data.append([
                        review_date, order_id, translated_details, uw_instructions, today
                    ])
                    
                    self.usage_stats["orders_processed"] += 1
                    
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
                "usage": self.get_usage_info()
            }
            
        except Exception as e:
            return {"success": False, "message": f"处理失败: {str(e)}"}

def main():
    """主函数"""
    
    # 页面标题
    st.title("📋 订单翻译工具")
    st.markdown("### ⚡ 零配置版本")
    
    # 初始化
    if 'translator' not in st.session_state:
        st.session_state.translator = OrderTranslator()
        st.session_state.initialized = False
    
    translator = st.session_state.translator
    
    # 检查初始化状态
    if not st.session_state.initialized:
        with st.spinner("🔄 正在初始化系统..."):
            st.session_state.initialized = translator.initialize_with_secrets()
    
    if not st.session_state.initialized:
        st.stop()
    
    # 成功初始化
    st.success("✅ 系统已就绪")
    
    # 主界面
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📅 选择处理日期")
        
        # 日期选项
        date_options = {
            "📅 今天的订单": datetime.now().date(),
            "📅 昨天的订单": datetime.now().date() - timedelta(days=1),
            "📅 最近3天": datetime.now().date() - timedelta(days=2),
            "📅 最近一周": datetime.now().date() - timedelta(days=6),
            "📅 从6月20日开始": datetime(2025, 6, 20).date(),
            "📅 本月全部": datetime(datetime.now().year, datetime.now().month, 1).date()
        }
        
        selected_option = st.selectbox(
            "选择日期范围",
            list(date_options.keys()),
            index=0  # 默认"从6月20日开始"
        )
        
        cutoff_date = date_options[selected_option]
        st.info(f"📊 将处理 **{cutoff_date}** 及以后的所有订单")
    
    with col2:
        st.subheader("📊 使用统计")
        usage_info = translator.get_usage_info()
        
        st.metric("已处理订单", usage_info['orders_processed'])
        st.metric("Token消耗", f"{usage_info['tokens_used']:,}")
        st.metric("预估成本", f"${usage_info['estimated_cost']:.3f}")
        
        # 系统状态
        if usage_info['estimated_cost'] < usage_info['monthly_budget'] * 0.8:
            st.success("💚 系统正常")
        else:
            st.warning("🟡 接近预算")
    
    # 处理按钮
    st.markdown("---")
    
    # 使用标准按钮避免兼容性问题
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        process_button = st.button(
            "🚀 开始翻译处理", 
            type="primary",
            use_container_width=True
        )
    
    if process_button:
        st.markdown("### 📊 处理进度")
        
        # 创建进度显示
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 开始处理
        cutoff_datetime = datetime.combine(cutoff_date, datetime.min.time())
        
        with st.spinner("正在处理订单..."):
            result = translator.process_orders(cutoff_datetime, progress_bar)
        
        # 显示结果
        if result["success"]:
            st.balloons()
            st.success(f"🎉 {result['message']}")
            
            # 显示统计
            final_usage = result["usage"]
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("✅ 处理完成", f"{result['count']} 订单")
            with col2:
                st.metric("🔤 Token使用", f"{final_usage['tokens_used']:,}")
            with col3:
                st.metric("💰 本次成本", f"${final_usage['estimated_cost']:.3f}")
            
            # 结果链接
            sheet_url = st.secrets.get("app_settings", {}).get("sheet_url",
                "https://docs.google.com/spreadsheets/d/1g_xoXrBy8MnG_76nrRAT9eNaMytE5YrCYBUK3q5AE04")
            
            st.markdown(f"""
            ### 📋 查看结果
            
            **✨ 翻译完成！** 结果已保存到工作表
            
            [🔗 点击查看结果]({sheet_url})
            
            **包含内容：**
            - Review Date（审核日期）
            - Order ID（订单编号）
            - Review Details（审核详情翻译）
            - UW Instructions（标准格式指令）
            - Processing Date（处理日期）
            """)
            
        else:
            st.error(f"❌ {result['message']}")

# 侧边栏
with st.sidebar:
    st.markdown("### ℹ️ 使用指南")
    st.markdown("""
    **🚀 使用步骤:**
    1. 选择日期范围
    2. 点击开始处理
    3. 等待处理完成
    4. 查看翻译结果
    
    **✨ 特点:**
    - 零配置使用
    - 自动格式识别
    - 实时进度显示
    - 成本统计
    """)
    
    # 格式说明
    if st.button("📖 查看输出格式"):
        st.markdown("""
        **需要电核订单:**
        ```
        ═══ THE APPROVAL RESULT... ═══
        ═══ NEED TO CALL... ═══
        [翻译内容]
        ═══ REVIEW ADVICE ═══
        [信审意见]
        ```
        
        **不需要电核订单:**
        ```
        ═══ THE APPROVAL RESULT... ═══
        [翻译内容]
        ═══ REVIEW ADVICE ═══
        [信审意见]
        ```
        """)

if __name__ == "__main__":
    main()
