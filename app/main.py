import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import requests


@dataclass
class FileState:
    size: int
    stable_checks: int
    first_seen_ts: float


class TelegramUploader:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: int = 120,
        max_retries: int = 5,
        retry_delay_sec: int = 5,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_sec = retry_delay_sec
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def verify_connection(self) -> None:
        url = f"{self.base_url}/getMe"
        for attempt in range(1, self.max_retries + 1):
            logging.info("Connecting to Telegram (attempt %d/%d)...", attempt, self.max_retries)
            try:
                resp = requests.get(url, timeout=self.timeout)
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get("ok"):
                    raise RuntimeError(f"Telegram API error: {payload}")
                bot_username = payload.get("result", {}).get("username", "<unknown>")
                logging.info("Connected to Telegram successfully. Bot username: @%s", bot_username)
                return
            except Exception as e:
                logging.warning(
                    "Failed to connect to Telegram (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_sec)
        raise RuntimeError(f"Unable to connect to Telegram after {self.max_retries} attempts")

    def _post_file(self, endpoint: str, file_path: Path, caption: str) -> None:
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(1, self.max_retries + 1):
            try:
                with file_path.open("rb") as f:
                    files = {
                        "video" if endpoint == "sendVideo" else "document": (
                            file_path.name,
                            f,
                            "application/octet-stream",
                        )
                    }
                    data = {"chat_id": self.chat_id, "caption": caption}
                    resp = requests.post(url, data=data, files=files, timeout=self.timeout)
                    resp.raise_for_status()
                    payload = resp.json()
                    if not payload.get("ok"):
                        raise RuntimeError(f"Telegram API error: {payload}")
                    return
            except Exception as e:
                logging.warning(
                    "Telegram upload failed for %s via %s (attempt %d/%d): %s",
                    file_path,
                    endpoint,
                    attempt,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_sec)
        raise RuntimeError(f"Upload failed after {self.max_retries} attempts: {file_path}")

    def upload_as_video(self, file_path: Path) -> None:
        self._post_file("sendVideo", file_path, caption=f"📹 {file_path.name}")

    def upload_as_document(self, file_path: Path) -> None:
        self._post_file("sendDocument", file_path, caption=f"📁 {file_path.name}")


class SurveillanceSync:
    def __init__(
        self,
        watch_dir: Path,
        uploader: TelegramUploader,
        polling_interval: int,
        stable_checks_required: int,
        min_file_age_sec: int,
        video_threshold_mb: int,
        archive_dir: Optional[Path] = None,
        recursive: bool = True,
        allowed_suffixes: Optional[set[str]] = None,
    ) -> None:
        self.watch_dir = watch_dir
        self.uploader = uploader
        self.polling_interval = polling_interval
        self.stable_checks_required = stable_checks_required
        self.min_file_age_sec = min_file_age_sec
        self.video_threshold_bytes = video_threshold_mb * 1024 * 1024
        self.archive_dir = archive_dir
        self.recursive = recursive
        self.allowed_suffixes = allowed_suffixes or {".mp4", ".mkv", ".avi", ".mov"}

        self.file_states: Dict[Path, FileState] = {}
        self.uploaded_record: set[Path] = set()

    def _iter_video_files(self):
        if self.recursive:
            candidates = self.watch_dir.rglob("*")
        else:
            candidates = self.watch_dir.glob("*")
        for p in candidates:
            if p.is_file() and p.suffix.lower() in self.allowed_suffixes:
                yield p

    def _is_ready(self, p: Path, now_ts: float) -> bool:
        stat = p.stat()
        age = now_ts - stat.st_mtime
        state = self.file_states.get(p)

        if state is None:
            self.file_states[p] = FileState(size=stat.st_size, stable_checks=0, first_seen_ts=now_ts)
            return False

        if stat.st_size == state.size:
            state.stable_checks += 1
        else:
            state.size = stat.st_size
            state.stable_checks = 0

        too_new = age < self.min_file_age_sec
        return state.stable_checks >= self.stable_checks_required and not too_new

    def _archive_or_delete(self, src: Path) -> None:
        if self.archive_dir:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            target = self.archive_dir / src.name
            if target.exists():
                target = self.archive_dir / f"{int(time.time())}_{src.name}"
            src.rename(target)
            logging.info("Moved uploaded file to archive: %s", target)
        else:
            src.unlink(missing_ok=True)
            logging.info("Removed uploaded file: %s", src)

    def _upload(self, p: Path) -> None:
        size = p.stat().st_size
        if size <= self.video_threshold_bytes:
            logging.info("Uploading as video: %s (%.2f MB)", p, size / 1024 / 1024)
            self.uploader.upload_as_video(p)
        else:
            logging.info("Uploading as document: %s (%.2f MB)", p, size / 1024 / 1024)
            self.uploader.upload_as_document(p)
        self.uploaded_record.add(p)

    def run_forever(self) -> None:
        logging.info("Start watching directory: %s", self.watch_dir)
        while True:
            now_ts = time.time()
            try:
                for p in self._iter_video_files():
                    if p in self.uploaded_record:
                        continue
                    try:
                        if self._is_ready(p, now_ts):
                            self._upload(p)
                            self._archive_or_delete(p)
                    except FileNotFoundError:
                        continue
                    except Exception as e:
                        logging.exception("Failed processing file %s: %s", p, e)
            except Exception as e:
                logging.exception("Scan loop error: %s", e)

            time.sleep(self.polling_interval)


def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def parse_suffixes(raw: str) -> set[str]:
    return {x.strip().lower() if x.strip().startswith(".") else f".{x.strip().lower()}" for x in raw.split(",") if x.strip()}


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    watch_dir = Path(os.getenv("WATCH_DIR", "/data/surveillance")).resolve()

    uploader = TelegramUploader(
        bot_token=bot_token,
        chat_id=chat_id,
        timeout=int(os.getenv("HTTP_TIMEOUT", "180")),
        max_retries=int(os.getenv("TELEGRAM_MAX_RETRIES", "5")),
        retry_delay_sec=int(os.getenv("TELEGRAM_RETRY_DELAY_SEC", "5")),
    )
    uploader.verify_connection()

    sync = SurveillanceSync(
        watch_dir=watch_dir,
        uploader=uploader,
        polling_interval=int(os.getenv("POLLING_INTERVAL_SEC", "15")),
        stable_checks_required=int(os.getenv("STABLE_CHECKS_REQUIRED", "3")),
        min_file_age_sec=int(os.getenv("MIN_FILE_AGE_SEC", "30")),
        video_threshold_mb=int(os.getenv("VIDEO_THRESHOLD_MB", "80")),
        archive_dir=Path(os.environ["ARCHIVE_DIR"]).resolve() if os.getenv("ARCHIVE_DIR") else None,
        recursive=env_bool("RECURSIVE_SCAN", True),
        allowed_suffixes=parse_suffixes(os.getenv("VIDEO_EXTENSIONS", ".mp4,.mkv,.avi,.mov")),
    )

    if not watch_dir.exists():
        raise FileNotFoundError(f"WATCH_DIR does not exist: {watch_dir}")

    sync.run_forever()


if __name__ == "__main__":
    main()
