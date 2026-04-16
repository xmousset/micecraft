from datetime import datetime, timedelta
from typing import List, Tuple, Any
from pathlib import Path
from enum import Enum
from tqdm import tqdm
import sys
import os

import pandas as pd


class LogLineParser:
    """Class for parsing one line of log and extracting relevant data.

    TAGS:
    -----
    """

    def __init__(self, log_line: str):
        self.log_line = log_line
        self.log_split = self.parse_log().split(" ")
        self.tag = self.log_split[0].strip("[]")
        self.is_warning = False
        if self.tag == "warning":
            self.is_warning = True
            self.tag = self.log_split[1].strip("[]")

    def parse_time(self) -> datetime:
        """Extract the time of the log line as a datetime format."""
        time = datetime.strptime(self.log_line[0:23], "%Y-%m-%d %H:%M:%S.%f")
        return time

    def parse_log(self) -> str:
        """Extract the log message from the log line."""
        return self.log_line[25:-1]


def get_phase(phase_str: str) -> str:
    match phase_str:
        case "HABITUATION":
            num = "01"
        case "INITIAL_TOUCH":
            num = "02"
        case "MUST_TOUCH":
            num = "03"
        case "VISUAL_DISCRIMINATION":
            num = "04"
        case "REVERSAL":
            num = "05"
        case "END":
            num = "06"
        case _:
            num = "00"
    return num + "_" + phase_str


def downloadData(exp_name: str, logs_path, pass_file):
    print("Start data download...")
    log_folder = str(logs_path)

    remoteDataFolder = "www/upload"
    import json
    import ftplib

    with open(pass_file) as f:
        connectData = json.load(f)

    session = ftplib.FTP_TLS(
        connectData["url"], connectData["login"], connectData["password"]
    )
    print(session)

    session.cwd(f"{remoteDataFolder}/")

    ls = []
    session.retrlines("MLSD", ls.append)
    session.cwd(f"/")
    for entry in ls:
        print(entry)

    onServerFiles = []
    for l in ls:
        s = l.split(";")[-1]
        s = s.strip()
        if "test" in s:  # skip if file contains "test"
            continue
        if exp_name in s and ".log.txt" in s:
            onServerFiles.append(s)

    for f in onServerFiles:
        print(f)

    for f in onServerFiles:
        print(f"Downloading {f}")
        localName = log_folder.rstrip("/") + "/" + f.lstrip("/")
        print(localName)
        with open(localName, "wb") as file:
            print(f)
            session.retrbinary(f"RETR {remoteDataFolder}/{f}", file.write)

    print("Downloads done.")


def merge_logs(logs_path):

    print("Start merging...")
    files = [
        f for f in logs_path.iterdir() if f.is_file() and f.suffix == ".txt"
    ]
    LogFileMerger(files, str(logs_path / "merged") + os.sep)
    print("Logs merged.")


class DataType(Enum):
    TRIAL = 1
    SENSOR = 2

    def __str__(self) -> str:
        return self.name


class MicecraftData:

    def __init__(self, data_type: DataType) -> None:
        self.type = data_type

    def set(
        self, attr: str, value: Any, print_overwrite_warning: bool = False
    ):
        """Set a data attribute. If overwrite, can send a warning."""
        current_value = self.get(attr)

        if current_value is None:
            setattr(self, attr, value)
            return

        # get cumulated value
        if attr[0:2] == "n_":
            setattr(self, attr, current_value + value)
            return

        # duration calculation
        if attr[0:2] == "d_":
            setattr(self, attr, value - current_value)
            return

        # overwrite
        setattr(self, attr, value)

        if not print_overwrite_warning:
            return

        # overwrite warning
        warning_exclusion = {
            "b_result": "INITIAL_TOUCH",
            "b_choose_left": "INITIAL_TOUCH",
            "b_reward_collected": "all",
            "x_touch": "INITIAL_TOUCH",
            "y_touch": "INITIAL_TOUCH",
        }

        if attr in warning_exclusion:
            if warning_exclusion[attr] != self.phase:
                tqdm.write(
                    f"[WARN] {attr} overwrite, {current_value} => {value}"
                )
        else:
            tqdm.write(f"[WARN] {attr} overwrite, {current_value} => {value}")

    def get(self, attr: str):
        return getattr(self, attr, None)

    def merge(self, other: "MicecraftData"):
        """Merge attributes values from another MicecraftData of same type."""
        if self.type != other.type:
            raise ValueError(f"Cannot merge {self.type} with {other.type}")

        all_attr = set(other.__dict__.keys())
        for attr in all_attr:
            self.set(attr, other.get(attr))

    def get_dict(self) -> dict:
        """Return non-None attributes as dict for DataFrame export."""
        dic = {
            k: v
            for k, v in self.__dict__.items()
            if (v is not None) and (k != "type")
        }
        return dic

    def complete(self):
        """Replace all 'None' in boolean data ('b_') with False."""
        completion_list = [
            "b_first_trial",
            # "b_reward_collected",
        ]
        for attr in completion_list:
            if self.get(attr) is None:
                self.set(attr, False)

    def final_calculation(self):

        all_attr = set(self.__dict__.keys())
        # compute only for TRIAL data
        if self.type != DataType.TRIAL:
            return

        self.n_touch_sum = 0
        self.d_state_sum = 0.0
        self.n_search_reward_sum = 0
        for attr in all_attr:
            if "n_touch_" in attr:
                n = self.get(attr)
                if n is not None:
                    self.n_touch_sum += n
            if "d_state_" in attr:
                # convert timedelta (duration) in seconds
                d = getattr(self, attr)
                if not isinstance(d, timedelta):
                    # tqdm.write(f"[WARN] {attr} is not a timedelta: {d}")
                    setattr(self, attr, timedelta(0).total_seconds())
                else:
                    setattr(self, attr, d.total_seconds())
                d = self.get(attr)
                if d is not None:
                    self.d_state_sum += d
            if "n_search_reward" in attr:
                n = self.get(attr)
                if n is not None:
                    self.n_search_reward_sum += n

    def __getattr__(self, name: str) -> Any:
        """For managing getting unknown attributes."""
        return None

    def __setattr__(self, name: str, value: Any):
        """For managing setting unknown attributes."""
        super().__setattr__(name, value)


class LogExtractor(object):

    def __init__(self, logFile: Path):
        self.file = logFile

        # list for DataFrame conversion
        self.sensors: List[dict] = []
        self.trials: List[dict] = []
        self.mice: dict = {}

        # get initial datetime
        self.zero = self.get_zero()

    def get_dataframe(self, dic_data):
        return pd.DataFrame(dic_data)

    def get_zero(self):
        with open(self.file) as f:
            line = f.readline()
            time, _ = self.get_time_and_log(line)
        return time

    def process(self):
        """Process each line of log file and extract data."""

        with open(self.file) as f:

            session_id = 0
            session_rfid = ""
            session_phase = ""
            in_session = False
            weight = None
            gate_wait_time = None
            gate_wait_duration = timedelta(seconds=0)
            state = ""
            trial = MicecraftData(DataType.TRIAL)
            self.mice["rfid"] = []

            lines = f.readlines()
            for line in tqdm(lines, desc="Processing log lines"):

                if line[0] != "2":
                    continue

                # -------------------------
                # separate time and log
                # -------------------------
                time, log = self.get_time_and_log(line)
                log_split = log.split(" ")
                tags = log_split[0:2]

                # -------------------------
                # gate wait time management
                # -------------------------
                if "[TraceLogic][gate][004] WAIT SINGLE_ANIMAL" in log:
                    if gate_wait_time is None:
                        gate_wait_time = time
                    else:
                        continue

                if "[TraceLogic][gate][005] CLOSE" in log:
                    if gate_wait_time is None:
                        continue
                    else:
                        gate_wait_duration += time - gate_wait_time
                        gate_wait_time = None

                # -------------------------
                # mice description
                # -------------------------
                if (
                    tags[0] == "[INFO]"
                    and "correct image distribution order" in log
                ):
                    self.mice["ts_image"] = log_split[-4:]
                    for i in range(len(self.mice["ts_image"])):
                        self.mice["ts_image"][i] = (
                            self.mice["ts_image"][i]
                            .replace("'", "")
                            .replace("]", "")
                            .replace("[", "")
                            .replace(",", "")
                        )
                    continue

                # [INFO] new RFID registered: 002030416719.
                if tags[0] == "[INFO]" and "new RFID registered" in log:
                    self.mice["rfid"].append(log_split[-1][:-1])
                    continue

                # -------------------------
                # sensors parameters
                # -------------------------
                if log[0] == "{":
                    sensors_data = self.parse_sensors_data(log)
                    sensors_data.time = time
                    self.sensors.append(sensors_data.get_dict())
                    continue

                # -------------------------
                # animal weight in gates
                # -------------------------
                if log_split[2:4] == ["WEIGHT", "OK:"]:
                    weight = float(log_split[-1])

                # -------------------------
                # RFID reading in gates
                # -------------------------
                if log[0:12] == "[RFID CHECK]":

                    # RFID reading occur before beggining a session
                    if in_session:
                        tqdm.write(
                            "[WARN] RFID read while in session "
                            f"at log:\n{time}: {log}"
                        )

                    if "read in:" == log_split[4] + " " + log_split[5]:
                        trial.set("n_rfid_read_in", int(log_split[6]))

                    if "Can't read ID" in log:
                        trial.set("n_rfid_read_fail", 1)

                # -------------------------
                # END of trial or session
                # -------------------------
                # END session if application restarted
                if tags[1] in ["[EXIT]", "started", "[TRIL]"]:

                    if not in_session and tags[1] != "started":
                        # tqdm.write(
                        #     f"[WARN] not in session when {tags[1]} occurs"
                        # )
                        # tqdm.write(f"{time}: {log}")
                        continue

                    if in_session and tags[1] == "started":
                        tqdm.write("[WARN] application restart during session")
                        tqdm.write(f"{time}: {log}")

                    if in_session:
                        trial.set("d_state_" + state, time)
                        state = ""
                        trial.set("t_end", time)
                        trial.set("weight", weight)
                        weight = None
                        trial.complete()
                        trial.final_calculation()
                        self.trials.append(trial.get_dict())
                        trial = MicecraftData(DataType.TRIAL)

                    if tags[1] != "[TRIL]":
                        in_session = False

                # -------------------------
                # BEGINNING of session
                # -------------------------
                # [DATA] animal 002035269670 begin session in Phase.MUST_TOUCH
                if tags[0] == "[DATA]" and log_split[3:5] == [
                    "begin",
                    "session",
                ]:
                    if in_session:
                        # tqdm.write(
                        #     "[WARN] already in session when beginning a new session"
                        # )
                        # tqdm.write(f"{time}: {log}")
                        trial.set("d_state_" + state, time)
                        trial.set("t_end", time)
                        trial.complete()
                        trial.final_calculation()
                        self.trials.append(trial.get_dict())
                        state = ""
                        trial = MicecraftData(DataType.TRIAL)

                    trial.set("b_first_trial", True)
                    trial.set("weight", weight)
                    trial.set("d_gate_wait", gate_wait_duration)
                    gate_wait_duration = timedelta(seconds=0)
                    weight = None
                    session_id += 1
                    session_rfid = log_split[2]
                    session_phase = get_phase(
                        log_split[-1].replace("Phase.", "")
                    )
                    in_session = True

                # -------------------------
                # BEGINNING of trial
                # -------------------------
                if tags[1] in ["[INIT]", "[TRIL]"]:
                    if not in_session:
                        # tqdm.write(
                        #     f"not in session when beginning a trial: {log}"
                        # )
                        continue

                    trial.set("id_session", session_id)
                    state = tags[1][1:-1].lower()
                    trial.set("d_state_" + state, time)
                    trial.set("rfid", session_rfid)
                    trial.set("phase", session_phase)
                    trial.set("t_begin", time)
                    continue

                # for speed and debugging
                if not in_session:
                    # tqdm.write(f"[WARN] not in session for log: {log}")
                    continue

                # -------------------------
                # STATE management
                # -------------------------
                if tags[1] in ["[WAIT]", "[FAIL]"]:
                    if tags[1] == "[WAIT]":
                        trial.set("b_reward_collected", False)
                    trial.set("d_state_" + state, time)
                    state = tags[1][1:-1].lower()
                    trial.set("d_state_" + state, time)
                    continue

                # -------------------------
                # get XY coordinates of touch
                # -------------------------
                if tags[0] == "[EVNT]" and "symbol xy touched" == " ".join(
                    log_split[1:4]
                ):
                    trial.set("n_touch_" + state, 1)
                    if not ("disabled," in log_split):
                        trial.set("x_touch", int(log_split[-1].split(",")[-2]))
                        trial.set("y_touch", int(log_split[-1].split(",")[-1]))
                    continue

                # -------------------------
                # get display information
                # -------------------------
                # if tags[0] == "[DVIC]" and "display" in log_split:
                #     side, result = map(str.lower, log_split[-1].split("_"))
                #     trial.set("s_" + side + "_display", log_split[-3].lower())

                #     if result == "(success)":
                #         trial.set("b_" + side + "_result", True)
                #     if result == "(fail)":
                #         trial.set("b_" + side + "_result", False)
                #     continue

                # BUG FIX: touchscreen display info sometimes logged with [DVIC] tag instead of [INFO]
                if tags[0] == "[DVIC]" and "touchscreen display" == " ".join(
                    log_split[1:3]
                ):
                    result = log_split[-1].lower()
                    side = log_split[-2].lower()
                    trial.set("s_" + side + "_display", log_split[-4].lower())

                    if result == "(success)":
                        trial.set("b_" + side + "_result", True)
                    if result == "(fail)":
                        trial.set("b_" + side + "_result", False)
                    continue

                # -------------------------
                # get trial outcome
                # -------------------------
                if tags[0] == "[DATA]" and tags[1] == "[ADD]":

                    if log_split[4] == "choose":
                        if log_split[-1] == "left":
                            trial.set("b_choose_left", True)
                        if log_split[-1] == "right":
                            trial.set("b_choose_left", False)

                    if log_split[2] == "trial":
                        if log_split[-1] == "success":
                            trial.set("b_result", True)
                        if log_split[-1] == "fail":
                            trial.set("b_result", False)

                    if log_split[4] == "pick":
                        trial.set("b_reward_collected", True)

                    continue

                # -------------------------
                # get correction trial info
                # -------------------------
                if tags[0] == "[DVIC]" and log_split[1] == "correction":
                    trial.set(
                        "right_correction_weight", float(log_split[-1][:-1])
                    )

                # -------------------------
                # get waterpump info
                # -------------------------
                if tags[0] == "[EVNT]" and log_split[1:] == ["animal", "in"]:
                    trial.set("n_search_reward_" + state, 1)

    def parse_sensors_data(self, log: str) -> MicecraftData:
        """Extract relevant data from one line of log."""

        # 'mean Pressure': 101.97646112600536, 'std Pressure': 0.004919918024744297, 'max Pressure': 101.99, 'min Pressure': 101.97,
        # 'mean Temperature': 23.98239946380697, 'std Temperature': 0.026719799162284508, 'max Temperature': 24.04, 'min Temperature': 23.9,
        # 'mean Humidity': 36.74843163538874, 'std Humidity': 0.14410798478232395, 'max Humidity': 37.01, 'min Humidity': 36.56,
        # 'mean r': 2.994638069705094, 'std r': 0.0730286245140817, 'max r': 3.0, 'min r': 2.0,
        # 'mean g': 2.0, 'std g': 0.0, 'max g': 2.0, 'min g': 2.0,
        # 'mean b': 1.8873994638069704, 'std b': 0.3161038681226026, 'max b': 2.0, 'min b': 1.0,
        # 'mean a': 6.924932975871314, 'std a': 0.26349946113256006, 'max a': 7.0, 'min a': 6.0,
        # 'mean Sound level': 121.98257372654156, 'std Sound level': 55.604727814334524, 'max Sound level': 561.0, 'min Sound level': 26.0,
        # 'mean Tilting x': 0.0, 'std Tilting x': 0.0, 'max Tilting x': 0.0, 'min Tilting x': 0.0,
        # 'mean Tilting y': 0.0, 'std Tilting y': 0.0, 'max Tilting y': 0.0, 'min Tilting y': 0.0,
        # 'mean Shock': 0.020764075067024126, 'std Shock': 0.0028511972960801207, 'max Shock': 0.03, 'min Shock': 0.01,
        # 'mean Raw accel x': -0.10486595174262735, 'std Raw accel x': 0.055192043409621784, 'max Raw accel x': 0.04, 'min Raw accel x': -0.29,
        # 'mean Raw accel y': 0.056367292225201066, 'std Raw accel y': 0.05935144748817348, 'max Raw accel y': 0.23, 'min Raw accel y': -0.12,
        # 'mean Raw accel z': 1.0099999999999998, 'std Raw accel z': 2.220446049250313e-16, 'max Raw accel z': 1.01, 'min Raw accel z': 1.01

        data = MicecraftData(DataType.SENSOR)
        list_str = log.strip("}{").split(", ")
        values = []
        for s in list_str:
            [_, value] = s.split(": ")
            values.append(float(value))
        data.pressure = values[0]
        data.pressure_std = values[1]
        data.temperature = values[4]
        data.temperature_std = values[5]
        data.humidity = values[8]
        data.humidity_std = values[9]
        data.light = values[24]
        data.light_std = values[25]
        data.sound = values[28]
        data.sound_std = values[29]

        return data

    def test(self):
        with open(self.file) as f:
            line = f.readline()
            time, log = self.get_time_and_log(line)
            print(time)
            # print(log)
        return
