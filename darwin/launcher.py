#!/usr/bin/env python3
"""
RUT Pipeline — Lanceur macOS
Interface tkinter : file picker + log area en temps réel.
Config depuis ~/Library/Application Support/RUTPipeline/.env
"""
from __future__ import annotations

import io
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from pathlib import Path

# ── Chemins (dev et .app bundle PyInstaller) ──────────────────────────────────

if getattr(sys, "frozen", False):
    _BASE = Path(sys._MEIPASS)          # intérieur du bundle
else:
    _BASE = Path(__file__).resolve().parent.parent   # darwin/ → racine projet

sys.path.insert(0, str(_BASE / "src"))
sys.path.insert(0, str(_BASE / "scripts"))

# ── Chemins config macOS ──────────────────────────────────────────────────────

APP_NAME   = "RUT Pipeline"
APP_ID     = "com.industriaspico.rutpipeline"
CONFIG_DIR = Path.home() / "Library" / "Application Support" / "RUTPipeline"
ENV_PATH   = CONFIG_DIR / ".env"

# ── Redirection stdout/stderr → queue (tkinter thread-safe) ──────────────────


class _QueueStream:
    """File-like object qui envoie chaque écriture dans une queue."""

    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def write(self, text: str) -> int:
        if text:
            self._q.put(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise io.UnsupportedOperation("fileno")


_log_q: queue.Queue = queue.Queue()
sys.stdout = _QueueStream(_log_q)   # type: ignore[assignment]
sys.stderr = _QueueStream(_log_q)   # type: ignore[assignment]


# ── Application ───────────────────────────────────────────────────────────────


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.resizable(False, False)
        self.geometry("600x460")
        self._running = False
        self._build_ui()
        self._check_config()
        self._poll_logs()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # En-tête
        hdr = tk.Frame(self, bg="#16213e", height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="  RUT Pipeline",
            bg="#16213e", fg="#e2e8f0",
            font=("Helvetica", 15, "bold"),
        ).pack(side="left", padx=16, pady=12)
        tk.Label(
            hdr, text="Industrias Pico",
            bg="#16213e", fg="#64748b",
            font=("Helvetica", 11),
        ).pack(side="right", padx=16)

        # Boutons d'action
        btn_frame = tk.Frame(self, pady=10)
        btn_frame.pack(fill="x", padx=16)
        self._btn_pdf = ttk.Button(
            btn_frame, text="Traiter un PDF…",
            command=self._pick_pdf, width=24,
        )
        self._btn_pdf.grid(row=0, column=0, padx=(0, 8))
        self._btn_docs = ttk.Button(
            btn_frame, text="Ingérer depuis Odoo Documents",
            command=self._ingest_docs, width=32,
        )
        self._btn_docs.grid(row=0, column=1)

        # Zone de log
        log_frame = tk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        tk.Label(log_frame, text="Journal", anchor="w",
                 font=("Helvetica", 11, "bold")).pack(anchor="w")
        self._log = scrolledtext.ScrolledText(
            log_frame, state="disabled", wrap="word",
            font=("Menlo", 10), bg="#0d1117", fg="#c9d1d9",
            insertbackground="white", height=18,
        )
        self._log.pack(fill="both", expand=True)

        # Barre de statut
        self._status = tk.StringVar(value="Prêt")
        tk.Label(
            self, textvariable=self._status, anchor="w",
            font=("Helvetica", 10), fg="#666",
        ).pack(fill="x", padx=12, pady=(0, 6))

    # ── Config ────────────────────────────────────────────────────────────────

    def _check_config(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not ENV_PATH.exists():
            self._append(
                f"⚠  Configuration introuvable : {ENV_PATH}\n\n"
                "   Créez ce fichier avec vos credentials Odoo :\n\n"
                "   ODOO_URL=https://industriaspico-industriaspico.odoo.com\n"
                "   ODOO_DB=industriaspico-industriaspico-main-14967325\n"
                "   ODOO_USER=...\n"
                "   ODOO_PASSWORD=...\n"
                "   AUDIT_DB_DSN=postgresql://pipeline:pipeline@localhost:5432/pipeline_audit\n\n"
            )
            messagebox.showwarning(
                APP_NAME,
                f"Fichier de configuration introuvable :\n{ENV_PATH}\n\n"
                "Créez ce fichier avec vos credentials Odoo\n"
                "avant de continuer.",
            )
        else:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=ENV_PATH, override=False)
            self._append(f"✅  Config chargée — {ENV_PATH}\n\n")

    # ── Log (thread-safe via after) ───────────────────────────────────────────

    def _append(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _poll_logs(self) -> None:
        """Draine la queue stdout/stderr toutes les 100 ms."""
        try:
            while True:
                self._append(_log_q.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    # ── Threads ───────────────────────────────────────────────────────────────

    def _run_in_thread(self, fn, *args) -> None:
        if self._running:
            messagebox.showinfo(APP_NAME, "Un traitement est déjà en cours.")
            return
        self._running = True
        self._btn_pdf.state(["disabled"])
        self._btn_docs.state(["disabled"])

        def _worker() -> None:
            try:
                fn(*args)
            except Exception as exc:
                print(f"\n❌  {type(exc).__name__}: {exc}")
            finally:
                self._running = False
                self.after(0, self._on_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_done(self) -> None:
        self._btn_pdf.state(["!disabled"])
        self._btn_docs.state(["!disabled"])

    # ── Actions ───────────────────────────────────────────────────────────────

    def _pick_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Choisir un RUT PDF",
            filetypes=[("PDF", "*.pdf"), ("Tous les fichiers", "*.*")],
        )
        if path:
            self._run_in_thread(self._process_pdf, path)

    def _ingest_docs(self) -> None:
        self._run_in_thread(self._process_docs)

    # ── Pipeline — PDF local ──────────────────────────────────────────────────

    def _process_pdf(self, path: str) -> None:
        self._status.set("Traitement en cours…")
        print(f"\n▶  {Path(path).name}\n")

        from unittest.mock import MagicMock
        from pipeline.runner import Pipeline
        from pipeline.odoo_client import OdooClient
        from pipeline.audit_log import AuditLog
        from pipeline.models import DocumentSource

        # MinIO optionnel — si non configuré, archivage désactivé
        if os.getenv("MINIO_ENDPOINT"):
            from pipeline.storage_client import StorageClient
            storage = StorageClient()
        else:
            storage = MagicMock()
            print("⚠  MINIO_ENDPOINT absent — archivage S3 désactivé\n")

        pipeline = Pipeline(storage=storage, odoo=OdooClient(), audit=AuditLog())
        result = pipeline.process(Path(path), source=DocumentSource.UPLOAD)

        if result.needs_hitl:
            self._status.set("Révision manuelle requise")
            print("\n⚠  Confiance insuffisante — révision manuelle requise")
        elif result.error:
            self._status.set("Erreur")
            print(f"\n❌  {result.error}")
        else:
            verb = "créé" if result.odoo_action and result.odoo_action.value == "created" else "mis à jour"
            self._status.set(f"Terminé — contact {verb}")
            print(f"\n✅  Contact {verb} (partner_id={result.odoo_partner_id}) — {result.duration_ms} ms")

    # ── Pipeline — Odoo Documents ─────────────────────────────────────────────

    def _process_docs(self) -> None:
        self._status.set("Ingestion Odoo Documents…")
        print("\n▶  Ingestion depuis Odoo Documents\n")

        from unittest.mock import MagicMock
        from pipeline.runner import Pipeline
        from pipeline.odoo_client import OdooClient
        from pipeline.audit_log import AuditLog
        from ingest_from_documents import DocumentsIngester, process_all

        odoo     = OdooClient()
        pipeline = Pipeline(storage=MagicMock(), odoo=odoo, audit=AuditLog())
        ingester = DocumentsIngester(odoo=OdooClient())

        count = process_all(ingester, pipeline)
        self._status.set(f"Terminé — {count} document(s)")
        print(f"\n✅  {count} document(s) traité(s)")


# ── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    App().mainloop()
