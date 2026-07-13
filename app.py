import streamlit as st
import pandas as pd
import zipfile
import io
import datetime

# 网页基本配置
st.set_page_config(page_title="CSV 批量过滤与合并工具", layout="centered")
st.title("📁 CSV/ZIP 批量合并与日期过滤")
st.write("支持上传多个 CSV 文件或 **ZIP 压缩包**，解压后自动根据您指定的日期范围过滤并合并数据。")

# --- 核心修复：初始化 Session State 缓存 ---
# 用来保存处理结果，防止点击下载按钮后页面刷新导致数据丢失
if 'processed_csv' not in st.session_state:
    st.session_state.processed_csv = None
    st.session_state.output_filename = ""
    st.session_state.result_msg = ""
    st.session_state.result_status = "" # 'success' 或 'error'

# 1. 自定义时间选择器
st.subheader("1. 选择需要过滤的时间范围")
default_start = datetime.date(2026, 7, 1)
default_end = datetime.date(2026, 7, 31)

start_date = st.date_input("开始日期", default_start)
end_date = st.date_input("结束日期", default_end)

if start_date > end_date:
    st.error("❌ 错误：开始日期不能晚于结束日期，请重新选择！")

# 2. 文件上传组件
st.subheader("2. 上传文件")
uploaded_files = st.file_uploader(
    "请选择 CSV 文件或 ZIP 压缩包 (支持多选及混合上传)", 
    type=['csv', 'zip'], 
    accept_multiple_files=True
)

def process_csv_bytes(file_bytes, display_name, start_ts, end_ts):
    """尝试不同编码读取二进制 CSV 数据并进行日期过滤"""
    # 核心修复：调整编码顺序，将 utf-8-sig 放在首位，最适合处理带有特殊符号的文件
    encodings_to_try = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'latin1']
    df = None
    
    for encoding in encodings_to_try:
        try:
            # 加入 encoding_errors='replace'，如果遇到个别坏字符直接替换为 ?，而不是整文件报错降级编码
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding, encoding_errors='replace')
            break
        except Exception:
            continue
    
    if df is None:
        st.warning(f"❌ 读取失败 {display_name}: 无法识别文件编码，已跳过。")
        return None

    try:
        df.columns = df.columns.str.strip()
        if 'Date' in df.columns:
            df['Date_Parsed'] = pd.to_datetime(df['Date'], errors='coerce')
            mask = (df['Date_Parsed'] >= start_ts) & (df['Date_Parsed'] <= end_ts)
            filtered_df = df.loc[mask].copy()
            
            if not filtered_df.empty:
                filtered_df['Source_File'] = display_name
                filtered_df = filtered_df.drop(columns=['Date_Parsed']) 
                return filtered_df
        else:
            st.warning(f"⚠️ {display_name} 中未找到 'Date' 列，已跳过。")
    except Exception as e:
        st.error(f"处理 {display_name} 内容时出错: {e}")
    return None

# 3. 开始处理按钮逻辑
if uploaded_files and start_date <= end_date:
    if st.button("🚀 开始处理并合并数据"):
        data_frames = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        total_files = len(uploaded_files)
        
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"正在读取文件: {file.name}...")
            file_bytes = file.read()
            
            if file.name.endswith('.zip'):
                try:
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                        for member in z.namelist():
                            if member.endswith('.csv') and not member.startswith('__MACOSX'):
                                member_bytes = z.read(member)
                                display_name = f"{file.name} -> {member.split('/')[-1]}"
                                filtered_df = process_csv_bytes(member_bytes, display_name, start_ts, end_ts)
                                if filtered_df is not None:
                                    data_frames.append(filtered_df)
                except Exception as e:
                    st.error(f"解压 {file.name} 失败: {e}")
            elif file.name.endswith('.csv'):
                filtered_df = process_csv_bytes(file_bytes, file.name, start_ts, end_ts)
                if filtered_df is not None:
                    data_frames.append(filtered_df)
            
            progress_bar.progress((i + 1) / total_files)
        
        status_text.text("扫描完成，正在生成结果...")
        
        # 将结果存入 session_state 缓存中
        if data_frames:
            final_combined_df = pd.concat(data_frames, ignore_index=True)
            # 导出为 utf-8-sig 确保 Excel 打开不乱码
            st.session_state.processed_csv = final_combined_df.to_csv(index=False, encoding='utf-8-sig')
            st.session_state.output_filename = f"Combined_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
            st.session_state.result_msg = f"🎉 处理完成！共成功合并了 {len(final_combined_df)} 条数据。"
            st.session_state.result_status = 'success'
        else:
            st.session_state.processed_csv = None
            st.session_state.result_msg = f"❌ 未找到符合 {start_date} 至 {end_date} 的数据。"
            st.session_state.result_status = 'error'

# 4. 独立于按钮之外的结果展示区 (依赖缓存)
if st.session_state.result_status == 'success':
    st.success(st.session_state.result_msg)
    st.download_button(
        label="⬇️ 下载合并后的 CSV 文件",
        data=st.session_state.processed_csv,
        file_name=st.session_state.output_filename,
        mime="text/csv"
    )
elif st.session_state.result_status == 'error':
    st.error(st.session_state.result_msg)
