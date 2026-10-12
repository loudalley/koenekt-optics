"""Background batch runner. Talks to the UI only through a queue."""
import json
import logging
import threading
import time

from koenekt_codecs import convert_grec

from .paths import reports_dir

log = logging.getLogger(__name__)


class BatchWorker(threading.Thread):
    """Converts ``items`` [(item_id, path)] one after another.

    Events put on ``events``:
        ("start", item_id)
        ("progress", item_id, fraction, text)
        ("done", item_id, result_dict)
        ("finished", summary_dict)
    """

    def __init__(self, items, output_dir, fmt, events):
        super().__init__(daemon=True, name="grec-batch")
        self.items = items
        self.output_dir = output_dir
        self.fmt = fmt
        self.events = events
        self.cancel = threading.Event()

    def run(self):
        results = []
        try:
            for item_id, path in self.items:
                if self.cancel.is_set():
                    break
                self.events.put(("start", item_id))
                last = [0.0]

                def progress(fraction, text, item_id=item_id):
                    # Throttle: the UI only needs a few updates per second.
                    now = time.monotonic()
                    if now - last[0] >= 0.15 or fraction >= 1:
                        last[0] = now
                        self.events.put(("progress", item_id, fraction, text))

                log.info("Converting %s -> %s (%s)", path, self.output_dir, self.fmt)
                result = convert_grec(path, self.output_dir, self.fmt, progress, self.cancel).to_dict()
                log.info("%s: %s %s", path, result["status"], result["message"])
                results.append(result)
                self.events.put(("done", item_id, result))
                if result["status"] == "cancelled":
                    break
        finally:
            self.events.put(("finished", self._summary(results)))

    def _summary(self, results):
        counts = {s: sum(r["status"] == s for r in results)
                  for s in ("converted", "skipped", "failed", "cancelled")}
        counts["warnings"] = sum(r["status"] == "converted" and bool(r["warnings"]) for r in results)
        report = None
        if results:
            report = reports_dir() / f"Conversion-{time.strftime('%Y%m%d-%H%M%S')}.json"
            try:
                report.write_text(json.dumps({"format": self.fmt, "output_dir": str(self.output_dir),
                                              "results": results}, indent=2), encoding="utf-8")
            except OSError as error:
                log.warning("Could not write report: %s", error)
                report = None
        return {"counts": counts, "report": str(report) if report else None,
                "cancelled": self.cancel.is_set()}
