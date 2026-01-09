from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import streamlit as st
import json

SCOPES = ["https://www.googleapis.com/auth/drive"]
REDIRECT_URI = "https://gdriveaccountsmanager-nu5f5kriwwayhzjhjrr9w6.streamlit.app/"

def start_oauth():
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": st.secrets["google_oauth"]["client_id"],
                "client_secret": st.secrets["google_oauth"]["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI]
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    flow.redirect_uri = REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    st.session_state.oauth_state = state
    st.link_button("🔐 Login with Google", auth_url)


def finish_oauth():
    if "code" not in st.query_params:
        return None

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": st.secrets["google_oauth"]["client_id"],
                "client_secret": st.secrets["google_oauth"]["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI]
            }
        },
        scopes=SCOPES,
        state=st.session_state.oauth_state,
    )

    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(code=st.query_params["code"])

    creds = flow.credentials
    st.session_state["drive_creds"] = creds
    return creds
