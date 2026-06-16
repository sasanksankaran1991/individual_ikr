"""Progressive Web App (PWA) — install on mobile home screen."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components


def inject_pwa() -> None:
    """Link manifest + mobile meta tags so users can Add to Home Screen."""
    manifest_href = "/app/static/manifest.webmanifest"
    icon_192 = "/app/static/icon-192.png"
    icon_svg = "/app/static/icon.svg"

    components.html(
        f"""
        <script>
        (function () {{
            const head = parent.document.head;
            if (!head || head.querySelector('link[data-ikr-manifest]')) return;

            function addLink(rel, href, extra) {{
                const el = parent.document.createElement('link');
                el.rel = rel;
                el.href = href;
                if (extra) Object.assign(el, extra);
                head.appendChild(el);
            }}

            function addMeta(name, content) {{
                const el = parent.document.createElement('meta');
                el.name = name;
                el.content = content;
                head.appendChild(el);
            }}

            addLink('manifest', '{manifest_href}', {{'data-ikr-manifest': '1'}});
            addMeta('theme-color', '#4f46e5');
            addMeta('mobile-web-app-capable', 'yes');
            addMeta('apple-mobile-web-app-capable', 'yes');
            addMeta('apple-mobile-web-app-status-bar-style', 'default');
            addMeta('apple-mobile-web-app-title', 'IKR');
            addLink('apple-touch-icon', '{icon_192}');
            addLink('icon', '{icon_svg}', {{type: 'image/svg+xml'}});

            if ('serviceWorker' in parent.navigator) {{
                const swUrl = '/app/static/sw.js';
                parent.navigator.serviceWorker.register(swUrl).catch(function () {{}});
            }}
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def render_mobile_install_hint() -> None:
    """Short instructions for installing as a phone app."""
    with st.expander("📱 Install on your phone", expanded=False):
        st.markdown(
            """
            **iPhone (Safari)**  
            1. Open this page in **Safari** (not Chrome)  
            2. Tap **Share** → **Add to Home Screen**  
            3. Tap **Add** — opens like an app (no browser bar)

            **Android (Chrome)**  
            1. Open in **Chrome**  
            2. Tap **⋮** menu → **Install app** or **Add to Home screen**

            **Same Wi‑Fi as your PC?**  
            On the server machine run Streamlit with network access, then on your phone open:
            `http://<computer-ip>:18501` (e.g. `http://192.168.1.5:18501`).

            Find your IP: Mac → Terminal → `ipconfig getifaddr en0` · Windows → `ipconfig`
            """
        )
