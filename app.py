import hmac
import io
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import urllib3

# 關閉 verify=False 產生的 SSL 警告訊息
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --------------------------------------------------------------------------------------
# 頁面基本設定 (必須為第一個 Streamlit 指令)
# --------------------------------------------------------------------------------------
st.set_page_config(
    page_title="TWSE 公開資訊觀測站 OpenData 檢核系統",
    page_icon="📊",
    layout="wide",
)


# --------------------------------------------------------------------------------------
# 密碼存取驗證閘道 (密碼儲存於 Streamlit Cloud Secrets，不寫死於公開程式碼中)
# --------------------------------------------------------------------------------------
def require_password() -> None:
    if st.session_state.get("authenticated", False):
        return

    st.title("🔒 系統存取驗證")
    st.caption("本系統已啟用密碼保護，請輸入授權密碼以進入檢核儀表板。")

    try:
        expected_password = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        expected_password = ""

    if not expected_password:
        st.error(
            "尚未偵測到密碼設定。請至 Streamlit Community Cloud 的 "
            "**App Settings → Secrets** 新增設定：\n\n"
            '```toml\nAPP_PASSWORD = "您自訂的密碼"\n```'
        )
        st.stop()

    with st.form("login_form", clear_on_submit=False):
        entered_password = st.text_input("存取密碼", type="password", placeholder="請輸入密碼")
        submitted = st.form_submit_button("登入系統", use_container_width=True)

    if submitted:
        if hmac.compare_digest(entered_password, str(expected_password)):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("密碼錯誤，請重新確認後再試。")

    st.stop()


require_password()

# --------------------------------------------------------------------------------------
# 預設常用 TWSE MOPS OpenData CSV 連結清單與追蹤標的
# --------------------------------------------------------------------------------------
PRESET_URLS = {
    "上市公司企業ESG資訊揭露 (t187ap46_L_1.csv)": "https://mopsfin.twse.com.tw/opendata/t187ap46_L_1.csv",
    "上市公司每月營業收入彙總表 (t187ap05_L.csv)": "https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv",
    "上市公司綜合損益表/EPS (t187ap14_L.csv)": "https://mopsfin.twse.com.tw/opendata/t187ap14_L.csv",
    "上市公司基本資料表 (t187ap03_L.csv)": "https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv",
    "自訂連結 (手動輸入 URL)": "",
}

DSX_POD_CODES = [
    "2308", "3017", "3324", "3665", "6805",
    "2233", "3013", "8996", "6781", "4938", "8926",
]


# --------------------------------------------------------------------------------------
# 資料抓取與解析函數 (快取 3600 秒避免頻繁請求遭阻擋)
# --------------------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_twse_csv(target_url: str, save_local: bool = True) -> pd.DataFrame:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(target_url, headers=headers, verify=False, timeout=30)
    response.raise_for_status()

    if save_local:
        with open("data01.csv", "wb") as file:
            file.write(response.content)

    try:
        df = pd.read_csv(io.BytesIO(response.content), encoding="utf-8-sig", dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(io.BytesIO(response.content), encoding="cp950", dtype=str)

    df.columns = [str(col).strip() for col in df.columns]
    return df


# --------------------------------------------------------------------------------------
# 側邊欄：參數設定與資料清理規則
# --------------------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 資料來源與檢核設定")

    selected_preset = st.selectbox(
        "選擇證交所 OpenData 報表",
        options=list(PRESET_URLS.keys()),
        index=0,
    )

    default_url = (
        PRESET_URLS[selected_preset]
        if PRESET_URLS[selected_preset]
        else "https://mopsfin.twse.com.tw/opendata/t187ap46_L_1.csv"
    )

    url = st.text_input(
        "CSV 資料連結 (可替換連結)",
        value=default_url,
        help="輸入證交所或政府資料開放平台之 CSV 下載網址",
    )

    dropna_mode = st.radio(
        "空值 (NA) 處理方式",
        options=[
            "移除任何含空值之資料列 (df.dropna())",
            "僅移除全部欄位皆為空值之列 (dropna how='all')",
            "保留全部原始資料列",
        ],
        index=0,
        help="部分證交所報表含有選填之『備註』欄位，若執行嚴格 dropna() 後筆數為 0，可切換為第 2 或第 3 項。",
    )

    filter_dsx_only = st.checkbox(
        "僅篩選 DSX POD 核心追蹤股",
        value=False,
        help="自動篩選公司代號：2308, 3017, 3324, 3665, 6805, 2233, 3013, 8996, 6781, 4938, 8926",
    )

    keyword_filter = st.text_input(
        "關鍵字 / 公司代號搜尋",
        value="",
        placeholder="例如：6781 或 台達電",
    )

    refresh_btn = st.button("🔄 重新抓取最新資料", use_container_width=True)
    if refresh_btn:
        st.cache_data.clear()

    if st.button("🔒 登出系統", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

# --------------------------------------------------------------------------------------
# 主畫面：資料載入、處理與呈現
# --------------------------------------------------------------------------------------
st.title("📊 TWSE 公開資訊觀測站 OpenData 數據檢核儀表板")
st.caption(f"目前資料來源：`{url}`")

if not url.strip():
    st.warning("請於左側邊欄輸入有效的 CSV 連結。")
    st.stop()

try:
    with st.spinner("正在從公開資訊觀測站載入 CSV 數據..."):
        raw_df = fetch_twse_csv(url.strip())
except Exception as exc:
    st.error(f"資料抓取或解析失敗，請確認網址是否正確。錯誤訊息：{exc}")
    st.stop()

raw_row_count = len(raw_df)
df = raw_df.copy()

if dropna_mode == "移除任何含空值之資料列 (df.dropna())":
    df = df.dropna()
    if len(df) == 0 and raw_row_count > 0:
        st.warning(
            f"提示：原始資料共 {raw_row_count:,} 筆，但因部分選填欄位（如備註欄）全為空值，"
            "執行嚴格 `df.dropna()` 後剩餘 0 筆。已自動改為移除全空欄位後再執行 `dropna()`。"
        )
        non_empty_cols = raw_df.dropna(axis=1, how="all").columns
        df = raw_df[non_empty_cols].dropna()
elif dropna_mode == "僅移除全部欄位皆為空值之列 (dropna how='all')":
    df = df.dropna(how="all")

code_col = next(
    (col for col in df.columns if "公司代號" in col or "證券代號" in col or col == "代號"),
    None,
)

if filter_dsx_only and code_col:
    df = df[df[code_col].astype(str).str.strip().isin(DSX_POD_CODES)]

if keyword_filter.strip():
    kw = keyword_filter.strip()
    mask = df.astype(str).apply(lambda col: col.str.contains(kw, case=False, na=False)).any(axis=1)
    df = df[mask]

# --------------------------------------------------------------------------------------
# 關鍵數據指標摘要
# --------------------------------------------------------------------------------------
col1, col2, col3 = st.columns(3)
col1.metric("原始資料總筆數", f"{raw_row_count:,}")
col2.metric("清理與篩選後筆數", f"{len(df):,}")
col3.metric("資料欄位數", f"{len(df.columns)}")

# --------------------------------------------------------------------------------------
# 資料表檢視與匯出下載
# --------------------------------------------------------------------------------------
st.subheader("📋 數據明細表")
st.dataframe(df, use_container_width=True, height=480)

csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
st.download_button(
    label="⬇️ 下載篩選後 CSV (UTF-8-SIG 繁體中文相容)",
    data=csv_bytes,
    file_name="data01_filtered.csv",
    mime="text/csv",
)

# --------------------------------------------------------------------------------------
# 量化欄位視覺化分析 (自動偵測可轉為數值之欄位)
# --------------------------------------------------------------------------------------
if len(df) > 0:
    numeric_candidates = []
    df_numeric = df.copy()
    exclude_keywords = ["代號", "日期", "年月", "年度", "統編", "統一編號", "電話"]

    for col in df.columns:
        if any(k in col for k in exclude_keywords):
            continue
        cleaned_series = (
            df[col]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False)
            .str.strip()
        )
        converted = pd.to_numeric(cleaned_series, errors="coerce")
        if converted.notna().sum() >= max(1, int(len(df) * 0.3)):
            df_numeric[col] = converted
            numeric_candidates.append(col)

    if numeric_candidates:
        st.subheader("📈 數值欄位排行與視覺化檢核")
        c_left, c_right, c_topn = st.columns([2, 2, 1])

        label_options = [col for col in df.columns if col not in numeric_candidates] or list(df.columns)
        default_label_idx = 0
        for idx, col in enumerate(label_options):
            if "簡稱" in col or "名稱" in col or "代號" in col:
                default_label_idx = idx
                break

        x_col = c_left.selectbox("選擇橫軸標籤欄位 (公司名稱/代號)", options=label_options, index=default_label_idx)
        y_col = c_right.selectbox("選擇縱軸數值指標", options=numeric_candidates, index=0)
        top_n = c_topn.number_input("顯示前 N 筆", min_value=5, max_value=100, value=20, step=5)

        plot_df = (
            df_numeric[[x_col, y_col]]
            .dropna(subset=[y_col])
            .sort_values(by=y_col, ascending=False)
            .head(int(top_n))
        )

        if not plot_df.empty:
            fig = px.bar(
                plot_df,
                x=x_col,
                y=y_col,
                text_auto=".2s",
                title=f"{y_col} — 前 {len(plot_df)} 名排行",
            )
            fig.update_layout(xaxis_tickangle=-45, height=420)
            st.plotly_chart(fig, use_container_width=True)