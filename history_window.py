"""Read-only session history viewer."""
import tkinter as tk
from tkinter import ttk
from fishing_history import GRADES, COLORS, sale_percent
from history_view import COLUMNS, LABELS, MODES, make_rows, sort_rows, display_row


class HistoryWindow:
    def __init__(self, parent, history, on_load=None, on_delete=None, is_busy=lambda: False):
        self.history = history
        self.current_history = history
        self.source_path = None
        self.is_busy = is_busy
        self.window = tk.Toplevel(parent)
        self.window.title("낚시 히스토리 · 오늘 기록")
        self.window.geometry("1380x700")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.timer = None
        self.version = -1
        self.sort_column = None
        self.sort_direction = 0
        controls = ttk.Frame(self.window, padding=8)
        controls.pack(fill="x")
        self.mode = tk.StringVar(value="모두보기")
        modes = MODES
        combo = ttk.Combobox(controls, textvariable=self.mode, values=modes, state="readonly", width=14)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        self.grade = tk.StringVar(value="전체")
        for grade in ("전체",) + GRADES:
            ttk.Radiobutton(controls, text=grade, value=grade, variable=self.grade, command=self.refresh).pack(side="left", padx=3)
        self.delete_button = ttk.Button(controls, text="지난 히스토리 영구 삭제", command=on_delete)
        self.delete_button.pack(side="right")
        self.load_button = ttk.Button(controls, text="히스토리 불러오기", command=on_load)
        self.load_button.pack(side="right", padx=4)
        ttk.Button(controls, text="오늘 히스토리", command=self.show_current).pack(side="right")
        self.revenue = ttk.Label(self.window, padding=(8, 6), font=("Malgun Gothic", 13, "bold"))
        self.revenue.pack(fill="x")
        self.summary = ttk.Label(self.window, padding=8, wraplength=1020)
        self.summary.pack(fill="x")
        self.detail = ttk.Label(self.window, padding=8, wraplength=1020)
        self.detail.pack(fill="x")
        frame = ttk.Frame(self.window)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.columns = COLUMNS
        self.tree = ttk.Treeview(frame, columns=self.columns, show="headings")
        for name, label, width in zip(self.columns, LABELS,
                (165, 60, 105, 130, 60, 65, 85, 95, 90, 90, 380)):
            self.tree.heading(name, text=label, command=lambda c=name: self.toggle_sort(c))
            self.tree.column(name, width=width, minwidth=45)
        for grade, color in COLORS.items():
            self.tree.tag_configure(grade, foreground=color)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.footer = ttk.Label(self.window, text="기록마다 실행 파일 옆 fishing-macro-history 폴더에 자동 저장됩니다. 미확인 값은 — 표시.", padding=8)
        self.footer.pack(fill="x")
        self.poll()

    def close(self):
        if self.timer:
            self.window.after_cancel(self.timer)
        self.window.destroy()

    def show_current(self):
        self.set_history(self.current_history)

    def set_history(self, history, path=None):
        self.history, self.source_path = history, path
        self.window.title("낚시 히스토리 · " + (str(path) if path else "오늘 기록"))
        self.footer.configure(text=(f"불러온 기록: {path} · 오늘 기록과 합쳐지지 않습니다." if path else
            "기록마다 실행 파일 옆 fishing-macro-history 폴더에 자동 저장됩니다. 미확인 값은 — 표시."))
        self.refresh()

    def poll(self):
        state = "disabled" if self.is_busy() else "normal"
        self.load_button.configure(state=state)
        self.delete_button.configure(state=state)
        if self.version != self.history.version:
            self.refresh()
        self.timer = self.window.after(1000, self.poll)

    def toggle_sort(self, column):
        if self.sort_column != column:
            self.sort_column, self.sort_direction = column, 1
        else:
            self.sort_direction = (self.sort_direction + 1) % 3
            if self.sort_direction == 0:
                self.sort_column = None
        self.refresh()

    def insert(self, values, grade=""):
        self.tree.insert("", "end", values=values, tags=(grade,))

    def refresh(self):
        records = self.history.snapshot()
        self.version = self.history.version
        grade = self.grade.get()
        if grade != "전체":
            records = [r for r in records if r.get('grade') == grade]
        fish = [r for r in records if r["kind"] == "fish"]
        raids = [r for r in records if r["kind"] == "raid"]
        sum_key = lambda rows, key: sum(r.get(key, 0) for r in rows)
        self.revenue.configure(text=f"총 판매수익 {sum_key(fish, 'gold'):,}G")
        self.summary.configure(text=(f"물고기 {len(fish):,}마리 · "
            f"획득 경험치 {sum_key(records, 'exp'):,} EXP · 진주 +{sum_key(records, 'pearls'):,}개 · "
            f"자동어 {sum(r['kind'] == 'auto' for r in records)}회 · "
            f"레이드 {sum_key(raids, 'gold'):,}G / 해신석 {sum_key(raids, 'stones'):,}개 · 달성 보상 {sum_key(records, 'bonus'):,}G"))
        totals = " / ".join(f"{g} {sum(r.get('grade') == g for r in fish):,}마리" for g in (GRADES if grade == "전체" else (grade,)))
        unknown_exp = sum('exp' not in r for r in fish)
        unknown_fish = sum('species' not in r for r in fish)
        self.detail.configure(text=totals + f"\n어종 미확인 {unknown_fish}건 · 획득 EXP 미표기 {unknown_exp}건 (합계에서 제외)")
        mode, grade = self.mode.get(), self.grade.get()
        rows = sort_rows(make_rows(records, mode, grade), self.sort_column, self.sort_direction)
        if mode == "구간별":
            groups = {}
            for record in fish:
                if grade != "전체" and record.get('grade') != grade:
                    continue
                key = (record['time'][:10], sale_percent(record))
                groups.setdefault(key, []).append(record)
            summaries = []
            for (date, band), group in sorted(groups.items(), key=lambda item: (item[0][0], -(item[0][1] or 0))):
                known = [r['gold'] for r in group if 'gold' in r]
                label = f'{band}%' if band is not None else '—'
                average = f'{sum(known)/len(known):,.1f}G' if known else '—'
                summaries.append(f'{date} {label}: {sum(known):,}G / 평균 {average}')
            self.detail.configure(text=self.detail.cget('text') + "\n" + ' · '.join(summaries))
        for column, label in zip(COLUMNS, LABELS):
            suffix = (' ▲' if self.sort_direction == 1 else ' ▼') if column == self.sort_column else ''
            self.tree.heading(column, text=label + suffix)
        position = self.tree.yview()
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for row in rows:
            self.insert(display_row(row), row['grade'])
        if position:
            self.tree.yview_moveto(position[0])
