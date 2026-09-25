from __future__ import annotations
import tkinter as tk
from tkinter import ttk

_COPY_LABELS = {"Копіювати", "Копіювати токен", "Копіювати токен вибраної сторінки"}
_AI_SECRET_LABELS = {"NVIDIA NIM API Key", "Google Gemini API Key", "Groq API Key", "Cloudflare Account ID", "Cloudflare API Token", "Запасна llama.cpp модель"}


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _hide_copy_secret_buttons(root) -> int:
    removed=0
    for widget in list(_walk(root)):
        if not isinstance(widget, ttk.Button):
            continue
        try: text=str(widget.cget("text") or "").strip()
        except Exception: continue
        if text in _COPY_LABELS or text.startswith("Копіювати токен"):
            try: widget.destroy(); removed += 1
            except Exception: pass
    return removed


def _compact_facebook(root) -> None:
    for frame in _walk(root):
        if not isinstance(frame, ttk.LabelFrame):
            continue
        try: title=str(frame.cget("text") or "")
        except Exception: continue
        if title != "Facebook Pages":
            continue
        token_widgets=[]
        for child in frame.winfo_children():
            if isinstance(child,(ttk.Entry, ttk.Label)):
                try: text=str(child.cget("text") or "") if isinstance(child,ttk.Label) else ""
                except Exception: text=""
                if isinstance(child,ttk.Entry) or "User Access Token" in text:
                    token_widgets.append(child)
        hidden={"value":False}
        for w in token_widgets:
            try: w.grid_remove()
            except Exception: pass
        def toggle():
            hidden["value"] = not hidden["value"]
            for w in token_widgets:
                try: w.grid() if hidden["value"] else w.grid_remove()
                except Exception: pass
            button.config(text="Сховати розширені" if hidden["value"] else "Розширені параметри")
        button=ttk.Button(frame,text="Розширені параметри",command=toggle)
        try: button.grid(row=1,column=2,sticky="w",padx=(8,0))
        except Exception: button.pack(anchor="w")
        return


def _compact_ai_router(root) -> None:
    for frame in _walk(root):
        if not isinstance(frame, ttk.LabelFrame):
            continue
        try: title=str(frame.cget("text") or "")
        except Exception: continue
        if not title.startswith("1. AI Router"):
            continue
        # Hide credential rows 2..7 by default. Controls remain available behind one explicit button.
        hidden_widgets=[]
        for row in range(2,8):
            try: hidden_widgets.extend(frame.grid_slaves(row=row))
            except Exception: pass
        for w in hidden_widgets:
            try: w.grid_remove()
            except Exception: pass
        state={"value":False}
        actions=None
        for child in frame.winfo_children():
            if isinstance(child,ttk.Frame):
                try:
                    if int(child.grid_info().get("row",-1))==8: actions=child; break
                except Exception: pass
        if actions is None: return
        def toggle():
            state["value"]=not state["value"]
            for w in hidden_widgets:
                try: w.grid() if state["value"] else w.grid_remove()
                except Exception: pass
            button.config(text="Сховати ключі" if state["value"] else "Показати ключі")
        button=ttk.Button(actions,text="Показати ключі",command=toggle)
        button.pack(side="left",padx=(10,0))
        return


def apply_ui_cleanup(root) -> dict[str,int]:
    removed=_hide_copy_secret_buttons(root)
    _compact_facebook(root)
    _compact_ai_router(root)
    return {"removed_secret_copy_buttons": removed}
