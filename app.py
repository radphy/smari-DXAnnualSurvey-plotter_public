import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import io

# =================================================================
# 1. AUTHENTICATION & SECURITY
# =================================================================
st.set_page_config(page_title="QA Plot Generator", page_icon="📊")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 Clinical QA Portal")
    pwd = st.text_input("Enter Department Passcode:", type="password")
    if st.button("Login"):
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect Passcode.")
    st.stop() # Stops the rest of the app from loading until authenticated

# =================================================================
# 2. APP CONFIGURATION (Sanitized)
# =================================================================
TABLE_IDS = {
    'SFS_KV': '20254', 'LFS_KV': '55647',
    'SFS_LIN': '54936', 'LFS_LIN': '55665'
}

TG_150_REFERENCE = {
    50: 1.83, 60: 2.92, 70: 4.13, 80: 5.25, 90: 6.97,
    100: 8.30, 110: 9.98, 120: 11.73
}

# =================================================================
# 3. DATA EXTRACTION
# =================================================================
def get_smari_json(label, report_id, api_key):
    auth_resp = requests.post('https://smari.phantomlab.com/api/rest/oauth', 
                             data={"client_id": label, "client_secret": api_key, "grant_type": "client_credentials"})
    if auth_resp.status_code == 200:
        token = auth_resp.json()['access_token']
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        data_resp = requests.get(f"https://smari.phantomlab.com/api/rest/report-data/{report_id}", headers=headers)
        if data_resp.status_code == 200: return data_resp.json()
    raise ConnectionError("API Authentication or Data Fetch Failed.")

def build_id_map(raw_json):
    id_map = {}
    def index(obj):
        if isinstance(obj, dict):
            if 'id' in obj: id_map[str(obj['id'])] = obj
            for v in obj.values(): index(v)
        elif isinstance(obj, list):
            for item in obj: index(item)
    index(raw_json)
    return id_map

def extract_table(raw_json, id_map, table_vid_str):
    def find_t(obj):
        if isinstance(obj, dict):
            vid = obj.get('variableId')
            if vid is not None and str(vid) == table_vid_str: return obj
            for v in obj.values():
                r = find_t(v)
                if r: return r
        elif isinstance(obj, list):
            for item in obj:
                r = find_t(item)
                if r: return r
    
    table_node = find_t(raw_json)
    if not table_node: return pd.DataFrame()

    cvs = table_node.get('childValues', [])
    unique_vids = []
    for cv in cvs:
        vid_str = str(cv.get('variableId'))
        if vid_str not in unique_vids and vid_str != 'None': unique_vids.append(vid_str)
    
    if not unique_vids: return pd.DataFrame()
    num_rows = sum(1 for cv in cvs if str(cv.get('variableId')) == unique_vids[0])
    
    rows = []
    for i in range(num_rows):
        row_data = {}
        for vid in unique_vids:
            occ = [cv for cv in cvs if str(cv.get('variableId')) == vid]
            if i < len(occ):
                node = id_map.get(str(occ[i].get('valueId')))
                if node: row_data[node.get('variableName') or vid] = node.get('value')
        rows.append(row_data)
        
    return pd.DataFrame(rows).apply(pd.to_numeric, errors='ignore')

def get_col(df, substring):
    for col in df.columns:
        if substring.lower() in str(col).lower(): return col
    return None

# =================================================================
# 4. USER INTERFACE & PLOTTING
# =================================================================
st.title("📊 Smári DX Annual Survey Plot Generator")
st.markdown("Enter the Smári Report ID from your finalized annual survey to generate the 2x2 PDF-scaled dashboard.")

report_id = st.text_input("Smári Report ID", placeholder="e.g. 123456")

if st.button("Generate Dashboard", type="primary"):
    if not report_id:
        st.warning("Please enter a valid Report ID.")
    else:
        with st.spinner(f"Extracting clinical data for Report {report_id} and rendering plots..."):
            try:
                # Pulls secure architecture from Streamlit Secrets
                api_key = st.secrets["SMARI_API_KEY"]
                client_label = st.secrets["CLIENT_LABEL"]
                
                raw_json = get_smari_json(client_label, report_id, api_key)
                id_map = build_id_map(raw_json)
                
                df_sfs_kv = extract_table(raw_json, id_map, TABLE_IDS['SFS_KV'])
                df_lfs_kv = extract_table(raw_json, id_map, TABLE_IDS['LFS_KV'])
                df_sfs_lin = extract_table(raw_json, id_map, TABLE_IDS['SFS_LIN'])
                df_lfs_lin = extract_table(raw_json, id_map, TABLE_IDS['LFS_LIN'])

                plt.rcParams.update({'font.size': 9, 'axes.titlesize': 11, 'axes.labelsize': 9, 'xtick.labelsize': 8, 'ytick.labelsize': 8, 'legend.fontsize': 8, 'lines.linewidth': 1.5, 'lines.markersize': 4})
                fig = plt.figure(figsize=(9, 9))

                # --- Plot 1: Output ---
                plt.subplot(2, 2, 1)
                for df, label, color in [(df_sfs_kv, 'SFS Output', 'tab:blue'), (df_lfs_kv, 'LFS Output', 'tab:orange')]:
                    if not df.empty and get_col(df, 'mr/mas') and get_col(df, 'nominal kv'):
                        df_plot = df.dropna(subset=[get_col(df, 'nominal kv'), get_col(df, 'mr/mas')]).sort_values(by=get_col(df, 'nominal kv'))
                        plt.plot(df_plot[get_col(df, 'nominal kv')], df_plot[get_col(df, 'mr/mas')], 'o-', label=label, color=color)
                plt.plot(list(TG_150_REFERENCE.keys()), list(TG_150_REFERENCE.values()), 's--', color='green', alpha=0.8, label='AAPM TG-150')
                plt.xlabel('Nominal kVp Station'); plt.ylabel('mR/mAs @ 100cm'); plt.title('Tube Output Performance'); plt.grid(True, linestyle='--', alpha=0.6)
                if plt.gca().get_legend_handles_labels()[0]: plt.legend(loc='upper left')

                # --- Plot 2: HVL ---
                plt.subplot(2, 2, 2)
                plotted_limits = False
                for df, label, color in [(df_sfs_kv, 'SFS HVL', 'tab:blue'), (df_lfs_kv, 'LFS HVL', 'tab:orange')]:
                    if not df.empty and get_col(df, 'measured hvl') and get_col(df, 'nominal kv'):
                        df_plot = df.dropna(subset=[get_col(df, 'nominal kv'), get_col(df, 'measured hvl')]).sort_values(by=get_col(df, 'nominal kv'))
                        plt.plot(df_plot[get_col(df, 'nominal kv')], df_plot[get_col(df, 'measured hvl')], 'o-', label=label, color=color)
                        if not plotted_limits and not df_plot.empty:
                            if get_col(df, '360.table'): plt.plot(df_plot[get_col(df, 'nominal kv')], df_plot[get_col(df, '360.table')], '--', color='red', label='IEMA Limit')
                            if get_col(df, '1020.30'): plt.plot(df_plot[get_col(df, 'nominal kv')], df_plot[get_col(df, '1020.30')], ':', color='purple', label='FDA Limit')
                            plotted_limits = True
                plt.xlabel('Nominal kVp Station'); plt.ylabel('HVL (mm Al)'); plt.title('HVL Compliance'); plt.grid(True, linestyle='--', alpha=0.6)
                handles, labels = plt.gca().get_legend_handles_labels()
                if handles:
                    data_hl, limit_hl = [(h, l) for h, l in zip(handles, labels) if 'Limit' not in l], [(h, l) for h, l in zip(handles, labels) if 'Limit' in l]
                    plt.legend([h for h, l in data_hl + limit_hl], [l for h, l in data_hl + limit_hl], loc='upper left')

                # --- Plot 3: Linearity ---
                plt.subplot(2, 2, 3)
                for df, label, color in [(df_sfs_lin, 'SFS Linearity', 'tab:blue'), (df_lfs_lin, 'LFS Linearity', 'tab:orange')]:
                    if not df.empty and get_col(df, 'mr @') and get_col(df, 'mas'):
                        df_plot = df.dropna(subset=[get_col(df, 'mas'), get_col(df, 'mr @')]).sort_values(by=get_col(df, 'mas'))
                        plt.plot(df_plot[get_col(df, 'mas')], df_plot[get_col(df, 'mr @')], 'o-', label=label, color=color)
                plt.xlabel('Nominal mAs Station'); plt.ylabel('Exposure (mR)'); plt.title('Output Linearity'); plt.grid(True, linestyle='--', alpha=0.6)
                if plt.gca().get_legend_handles_labels()[0]: plt.legend(loc='upper left')

                # --- Plot 4: Accuracy ---
                plt.subplot(2, 2, 4)
                for df, label, color in [(df_sfs_kv, 'SFS kVp Error', 'tab:blue'), (df_lfs_kv, 'LFS kVp Error', 'tab:orange')]:
                    if not df.empty and get_col(df, 'kv accuracy') and get_col(df, 'nominal kv'):
                        df_plot = df.dropna(subset=[get_col(df, 'nominal kv'), get_col(df, 'kv accuracy')]).sort_values(by=get_col(df, 'nominal kv'))
                        plt.plot(df_plot[get_col(df, 'nominal kv')], df_plot[get_col(df, 'kv accuracy')], 'o-', label=label, color=color)
                for df, label, color in [(df_sfs_lin, 'SFS Timer Error', 'cyan'), (df_lfs_lin, 'LFS Timer Error', 'pink')]:
                    if not df.empty and get_col(df, 'timer accuracy'):
                        x_col = get_col(df, 'timer') or get_col(df, 'mas')
                        if x_col:
                            df_plot = df.dropna(subset=[x_col, get_col(df, 'timer accuracy')]).sort_values(by=x_col)
                            plt.plot(df_plot[x_col], df_plot[get_col(df, 'timer accuracy')], 's-', label=label, color=color)
                plt.axhline(10, color='red', linestyle='--', alpha=0.7, label='+/- 10% Limit'); plt.axhline(-10, color='red', linestyle='--', alpha=0.7)
                plt.axhline(0, color='black', linewidth=1, alpha=0.5) 
                plt.xlabel('Nominal Set Point'); plt.ylabel('Deviation (%)'); plt.title('Generator Accuracy'); plt.grid(True, linestyle='--', alpha=0.6)
                handles, labels = plt.gca().get_legend_handles_labels()
                if handles:
                    data_hl, limit_hl = [(h, l) for h, l in zip(handles, labels) if 'Limit' not in l], [(h, l) for h, l in zip(handles, labels) if 'Limit' in l]
                    unique_limits = []
                    for h, l in limit_hl:
                        if l not in [ul for uh, ul in unique_limits]: unique_limits.append((h, l))
                    plt.legend([h for h, l in data_hl + unique_limits], [l for h, l in data_hl + unique_limits], loc='best')

                plt.tight_layout(pad=1.5, w_pad=2.0, h_pad=2.0)
                
                # Save plot to in-memory buffer at 600 DPI with transparency
                buf = io.BytesIO()
                plt.savefig(buf, format="png", dpi=600, bbox_inches='tight', transparent=True)
                buf.seek(0)
                
                # Display success and download button
                st.success("Dashboard successfully generated!")
                st.download_button(
                    label="📥 Download Dashboard Image",
                    data=buf,
                    file_name=f"smari_dashboard_{report_id}.png",
                    mime="image/png",
                    type="primary"
                )
                
                # Show a preview on the web page
                st.image(buf, caption="Dashboard Preview (Scaled for PDF)", use_container_width=True)

            except Exception as e:
                st.error(f"Data retrieval failed: {e}. Verify the Report ID and ensure the Smári report is saved.")

