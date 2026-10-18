"""逐批保留原始报价和推进时钟；每次启动新分片，不覆盖旧行情。"""
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

class Recorder:
    def __init__(self,data_dir,flush_every=300):
        self.data_dir=Path(data_dir)
        self.session=uuid4().hex
        self.sequence=0

    def event(self,kind,time,quotes=()):
        self.data_dir.mkdir(parents=True,exist_ok=True)
        self.sequence+=1
        row={"kind":kind,"time":time.isoformat(),"seq":self.sequence,"quotes":[asdict(q) for q in quotes]}
        path=self.data_dir / f"events_{time:%Y%m%d}_{self.session}.jsonl"
        with path.open("a",encoding="utf-8") as f:
            f.write(json.dumps(row,default=str,ensure_ascii=False,allow_nan=False)+"\n")
            f.flush()

    def add(self,quotes,time=None):
        if quotes:
            self.event("quotes",time or max(q.time for q in quotes),quotes)

    def flush(self):
        pass
