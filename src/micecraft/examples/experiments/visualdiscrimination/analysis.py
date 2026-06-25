import os
import sys
from enum import Enum
from pathlib import Path
from typing import List, Tuple, Any
from datetime import datetime, timedelta

import pandas as pd
from tqdm import tqdm

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from micecraft.soft.report.LogFileMerger import LogFileMerger


class LogLineParser:
    """Class for parsing one line of log and extracting relevant data."""

    @staticmethod
    def separate_room_device(device_name: str) -> Tuple[str, str]:
        """Separate the room name and the device name from a string of format
        'room-device'. Also remove any brackets ("[", "]") around the input
        device name.

        Returns:
            (room, device): A tuple containing the room name and the device
            name.
        """
        device_name = device_name.strip("[]")
        split = device_name.split("-")
        room = split[0]
        device = split[1]
        return room, device

    def __init__(self, log_line: str):
        self.log_line = log_line
        self.log_split = self.get_log().split(" ")
        self.tag, self.warning = self.get_tag()

    def get_tag(self) -> Tuple[str, bool]:
        """Extract the tags of the log line."""
        tag = self.log_split[0]
        warning = False
        if tag == "[warning]":
            warning = True
            tag = self.log_split[1]

        return tag, warning

    def get_time(self) -> datetime:
        """Extract the time of the log line as a datetime format."""
        time = datetime.strptime(self.log_line[0:23], "%Y-%m-%d %H:%M:%S.%f")
        return time

    def get_log(self) -> str:
        """Extract the log message from the log line. Begin after the ': ' that
        follows the timestamp."""
        return self.log_line[25:-1]

    def get_info(self, name: str) -> str | None:
        """Extract the information from the log line."""
        if not name.endswith(":"):
            name += ":"
        for i, s in enumerate(self.log_split):
            if s == name:
                return self.log_split[i + 1]
        return None

    def get_room(self) -> str:
        """Extract the room name from the log line."""
        room_name = self.get_info("room")
        if room_name is None:
            room_device = self.get_info("room-device")
            if room_device is None:
                raise ValueError(
                    f"Room name not found in log line:\n {self.log_line}"
                )
            room_name, _ = self.separate_room_device(room_device)
        return room_name

    def get_sensors_data(self) -> dict[str, float]:
        """Extract relevant data from one line of log."""
        data: dict[str, float] = {}
        list_str = self.log_line.strip("}{").split(", ")
        values = []
        for s in list_str:
            [_, value] = s.split(": ")
            values.append(float(value))
        data["pressure"] = values[0]
        data["pressure_std"] = values[1]
        data["temperature"] = values[4]
        data["temperature_std"] = values[5]
        data["humidity"] = values[8]
        data["humidity_std"] = values[9]
        data["light"] = values[24]
        data["light_std"] = values[25]
        data["sound"] = values[28]
        data["sound_std"] = values[29]

        return data


class TrialData:

    def __init__(self, session_id: int, room: str) -> None:

        self.current_state: str = "UNKNOWN"
        """Current state of the room."""

        self.session_id = session_id
        """The session ID for the trial. Indepedent from the animal."""
        self.room = room
        """The room where the trial took place."""
        self.left_display: str | None = None
        """The image displayed on the left side of the touchscreen."""
        self.right_display: str | None = None
        """The image displayed on the right side of the touchscreen."""
        self.solution_image: str | None = None
        """The image corresponding to the correct answer for the trial."""
        self.touch_left: bool | None = None
        """The side touched by the animal for the trial answer.
        None if no touch."""
        self.trial_result: bool | None = None
        """Result of the trial (True if correct, False if incorrect)."""
        self.x_touch: float | None = None
        """X position of the answer (touch). Other touches coordinates are not
        stored."""
        self.y_touch: float | None = None
        """Y position of the answer (touch). Other touches coordinates are not
        stored."""
        self.reward_collected: bool | None = None
        """Animal got the reward."""

        self.state_start: dict[str, datetime] = {}
        """States start time."""
        self.state_end: dict[str, datetime] = {}
        """States end time."""
        self.state_searches: dict[str, int] = {}
        """Number of searches during a state (went inside water pump)."""
        self.state_touches: dict[str, int] = {}
        """Number of touches during a state."""

    def as_dict(self) -> dict:
        """Return as dict for DataFrame export."""
        state_duration: dict[str, timedelta | None] = {}
        trial_start = datetime.max
        for state in self.state_start.keys():
            start = self.state_start[state]
            if start < trial_start:
                trial_start = start
            end = self.state_end[state]
            if start and end:
                state_duration[state] = end - start
            else:
                state_duration[state] = None

        return {
            "session_id": self.session_id,
            "room": self.room,
            "trial_time": trial_start,
            "left_display": self.left_display,
            "right_display": self.right_display,
            "solution_image": self.solution_image,
            "touch_left": self.touch_left,
            "trial_result": self.trial_result,
            "x_touch": self.x_touch,
            "y_touch": self.y_touch,
            "reward_collected": self.reward_collected,
            **{f"{k}_state_duration": v for k, v in state_duration.items()},
            **{
                f"{k}_state_searches": v
                for k, v in self.state_searches.items()
            },
            **{f"{k}_state_touches": v for k, v in self.state_touches.items()},
        }


class SessionData:

    _id_counter: int = 0

    def __init__(self, room_name: str) -> None:
        self.session_id = SessionData._id_counter
        """The session ID for the trial. Indepedent from the animal."""
        SessionData._id_counter += 1

        self.room: str = room_name
        """Name of the room where the session took place."""
        self.rfid_reading_failure: int = 0
        """Number of failed RFID readings before this session."""
        self.rfid_read_in: int | None = None
        """Number of attempted RFID readings before this session."""
        self.phase: str | None = None
        """Current phase of the animal for this session."""
        self.rfid: str | None = None
        """RFID number of the animal in the session."""
        self.start_time: datetime | None = None
        """Session start time."""
        self.end_time: datetime | None = None
        """Session end time."""
        self.weight_in: float | None = None
        """Animal weight measured in the gate when beginning session."""
        self.weight_out: float | None = None
        """Animal weight measured in the gate when ending session."""

    def as_dict(self) -> dict:
        """Return as dict for DataFrame export."""

        return {
            "session_id": self.session_id,
            "rfid": self.rfid,
            "room": self.room,
            "phase": self.phase,
            "weight_in": self.weight_in,
            "weight_out": self.weight_out,
            "rfid_read_in": self.rfid_read_in,
            "rfid_reading_failure": self.rfid_reading_failure,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


class AnimalData:
    def __init__(self, rfid: str) -> None:
        self.rfid: str = rfid
        """RFID number of the animal."""
        self.ts_image: str | None = None
        """Attributed touch screen image."""


class LogAnalyzer(object):

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.sensors: list[dict[str, Any]] = []
        self.sessions: list[SessionData] = []
        self.trials: list[TrialData] = []

        self.animals: list[AnimalData] = []
        """List of animals' data (RFID and attributed touch screen image)."""

        self.zero = self.get_zero()

    def get_zero(self):
        with open(self.log_file) as f:
            line = f.readline()
            parser = LogLineParser(line)
            time_zero = parser.get_time()
        return time_zero

    def to_csv(self) -> Tuple[Path, Path, Path]:
        """Export the extracted data to csv files and return their paths as
        *(sensors, sessions, trials)*."""
        folder_path = self.log_file.parent
        file_name = str(self.log_file).strip(".txt").strip(".log")

        sensors_df = pd.DataFrame(self.sensors)
        sensors_csv_path = folder_path / f"{file_name}.sensors.csv"
        sensors_df.to_csv(sensors_csv_path, index=False)

        sessions_df = pd.DataFrame([s.as_dict() for s in self.sessions])
        sessions_csv_path = folder_path / f"{file_name}.sessions.csv"
        sessions_df.to_csv(sessions_csv_path, index=False)

        trials_df = pd.DataFrame([t.as_dict() for t in self.trials])
        trials_csv_path = folder_path / f"{file_name}.trials.csv"
        trials_df.to_csv(trials_csv_path, index=False)

        return sensors_csv_path, sessions_csv_path, trials_csv_path

    def process_log(self):
        """Process each line of log file and extract data."""

        with open(self.log_file) as f:

            # (room_name: Data)
            # keep track of sessions and trials in all rooms at the same time
            trial: dict[str, TrialData] = {}
            session: dict[str, SessionData] = {}

            lines = f.readlines()
            for line in tqdm(lines, desc="Parsing log files"):

                # sort out irrelevant data
                # ----------------
                # (relevant line always start at least with the year, so "2")
                if line[0] != "2":
                    continue

                # initialise parser
                # ----------------
                parser = LogLineParser(line)

                if parser.warning:
                    continue

                # Rooms initialisation
                # ----------------
                if parser.tag == "[all_rooms]" and not session:
                    # r
                    rooms_name = parser.log_split[1:]
                    session = {name: SessionData(name) for name in rooms_name}
                    trial = {
                        name: TrialData(session[name].session_id, name)
                        for name in rooms_name
                    }
                    continue

                # Animal registration
                # ----------------
                if parser.tag == "[rfid_registration]":
                    # rfid: 000000000000 phase: 00-BLACK_WHITE
                    rfid = parser.get_info("rfid")
                    assert rfid is not None, f"{parser.tag} bug"
                    self.animals.append(AnimalData(rfid))
                    continue

                if parser.tag == "[ts_image_attribution]":
                    # rfid: 000000000000 ts_image: FLOWER
                    rfid = parser.get_info("rfid")
                    assert rfid is not None, f"{parser.tag} bug"
                    for animal in self.animals:
                        if animal.rfid == rfid:
                            animal.ts_image = parser.get_info("ts_image")
                    continue

                # Sensors
                # ----------------
                if parser.get_log() == "{'mean Pressure':":
                    self.sensors.append(parser.get_sensors_data())
                    continue

                # Animal weight
                # ----------------
                if "[animal_weight]" in parser.get_log():
                    # room: r-d rfid: 000000000000 weight_(g): 23.00
                    room = parser.get_room()
                    if session[room].rfid is None:
                        session[room].weight_in = float(parser.log_split[-1])
                    else:
                        session[room].weight_out = float(parser.log_split[-1])
                    continue

                # RFID reading
                # ----------------
                if "[RFID CHECK]" == parser.get_log()[0:12]:
                    # [RFID CHECK][rA-Gate] RFID 000000000000 read in: 3 / 100 time: 0.33 seconds side: TO SIDE B
                    room_device = parser.get_log()[13:].split(" ")[0]
                    room, _ = parser.separate_room_device(room_device)

                    if session[room].rfid is not None:
                        tqdm.write(
                            "RFID read while in session in log:\n "
                            f"{parser.log_line}"
                        )

                    if "read in:" in parser.get_log():
                        nb_read_in = parser.get_info("in")
                        if nb_read_in is not None:
                            session[room].rfid_read_in = int(nb_read_in)

                    if "Can't read ID" in parser.get_log():
                        session[room].rfid_reading_failure += 1
                    continue

                # Session end
                # ----------------
                # END session if application restarted or if animal exit room

                if parser.get_log() == "application started":
                    for room in session.keys():
                        if session[room].rfid is not None:
                            tqdm.write("Application restarted during session.")
                            session[room].end_time = parser.get_time()
                            self.sessions.append(session[room])
                            session[room] = SessionData(room)
                        if (
                            room in trial
                            and trial[room].current_state != "UNKNOWN"
                        ):
                            tqdm.write("Application restarted during trial.")
                            self.trials.append(trial.pop(room))
                    continue

                if parser.tag == "[animal_out]":
                    # room: r animal: 000000000000
                    room = parser.get_room()

                    if session[room].rfid is None:
                        continue
                    else:
                        session[room].end_time = parser.get_time()
                        self.sessions.append(session[room])
                        session[room] = SessionData(room)
                    continue

                # Session start
                # ----------------
                if parser.tag == "[animal_in]":
                    # room: r animal: 000000000000
                    room = parser.get_room()

                    if session[room].rfid is not None:
                        tqdm.write(
                            "Animal entered while in session in log:\n "
                            f"{parser.log_line}"
                        )
                        self.sessions.append(session[room])
                        session[room] = SessionData(room)

                    session[room].rfid = parser.get_info("rfid")
                    session[room].phase = parser.get_info("phase")
                    session[room].start_time = parser.get_time()
                    continue

                # State
                # ----------------
                if parser.tag == "[room_state]":
                    # room: r state: TRIAL
                    room = parser.get_room()

                    if session[room].rfid is None:
                        continue

                    state = parser.get_info("state")
                    if state is None:
                        tqdm.write(
                            "Unknown state in log:\n " f"{parser.log_line}"
                        )
                        continue

                    if room not in trial:
                        if state in ["INITIAL"]:
                            trial[room] = TrialData(
                                session[room].session_id,
                                room,
                            )
                            trial[room].current_state = state
                            trial[room].state_start[state] = parser.get_time()
                            continue

                    if trial[room].current_state in trial[room].state_start:
                        trial[room].state_end[
                            trial[room].current_state
                        ] = parser.get_time()

                    if state == "EXIT":
                        self.trials.append(trial.pop(room))
                        continue

                    if state == "TRIAL":
                        if trial[room].current_state != "INITIAL":
                            self.trials.append(trial.pop(room))
                            trial[room] = TrialData(
                                session[room].session_id,
                                room,
                            )

                    if state not in ["CLEAR", "EXIT"]:
                        trial[room].current_state = state
                        trial[room].state_start[state] = parser.get_time()
                    continue

                # Touch screen display
                # ----------------
                if parser.tag == "[touchscreen_display]":
                    # room-device: r-TS left: PLANE right: FLOWER id_left: 0 id_right: 1
                    room = parser.get_room()
                    trial[room].left_display = parser.get_info("left")
                    trial[room].right_display = parser.get_info("right")

                # Touches
                # ----------------
                if parser.tag == "[useful_touch]":
                    # room: r rfid: 000000000000 image_name: left_image_FLOWER image_id: 1 image_x: 560.0 image_y: 750.0 touch_x: 100 touch_y: 300
                    room = parser.get_room()
                    x = parser.get_info("touch_x")
                    y = parser.get_info("touch_y")
                    if x is not None:
                        trial[room].x_touch = float(x)
                    if y is not None:
                        trial[room].y_touch = float(y)
                    continue

                if parser.tag == "[useless_touch]":
                    # room: r rfid: 000000000000 touch_x: 100 touch_y: 300
                    room = parser.get_room()
                    trial[room].state_touches[trial[room].current_state] += 1
                    continue

                # Trial result
                # ----------------
                if parser.tag == "[trial_result]":
                    # room: r rfid: 000000000000 attribution: FLOWER phase: 00-BLACK_WHITE solution: LIGHT chosen_side: left result: FAIL
                    room = parser.get_room()
                    trial[room].solution_image = parser.get_info("solution")

                    result = parser.get_info("result")
                    if result == "SUCCESS":
                        trial[room].trial_result = True
                    elif result == "FAIL":
                        trial[room].trial_result = False

                    side = parser.get_info("chosen_side")
                    if side == "left":
                        trial[room].touch_left = True
                    elif side == "right":
                        trial[room].touch_left = False
                    continue

                # Reward picking
                # ----------------
                if parser.tag == "[reward_search]":
                    # room: r rfid: 000000000000 find: reward
                    room = parser.get_room()

                    info = parser.get_info("find")
                    if info == "reward":
                        trial[room].reward_collected = True
                    if info == "nothing":
                        trial[room].reward_collected = False

                    state = trial[room].current_state
                    if state not in trial[room].state_searches:
                        trial[room].state_searches[state] = 1
                    else:
                        trial[room].state_searches[state] += 1


def select_files(file_type: str) -> list[Path]:
    """Open a dialog to select at least one file of the specified type."""
    file_type = file_type.strip(".").lower()
    while True:
        files, _ = QFileDialog.getOpenFileNames(
            None,
            f"Select {file_type.upper()} files",
            str(Path.home()),
            f"{file_type.upper()} files (*.{file_type});;All files (*)",
        )
        if not files:
            sys.exit(0)

        files_list = [Path(f) for f in files if f.endswith(f".{file_type}")]
        if files_list:
            return files_list

        QMessageBox.warning(
            None,
            f"No {file_type.upper()} files found",
            (
                f"The selected files do not contain any .{file_type} file.\n"
                f"Please select valid {file_type.upper()} files."
            ),
        )


def merge_logs(log_files: list[Path]) -> Path:
    """Merge the selected log files and return the path for log analysis."""

    if len(log_files) == 1:
        return log_files[0]

    merged_path = log_files[0].parent / "merged"
    merged_path.mkdir(exist_ok=True)

    print("Start merging...")
    merger = LogFileMerger(log_files, str(merged_path) + os.sep)
    print("Logs merged.")

    return Path(merger.mergedFiles[0])


class AnalysisOptionDialog(QDialog):
    """Dialog asking the user which analysis option to run."""

    LOGS = 0
    ORIGINAL_CSV = 1
    COMPUTED_CSV = 2

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Analysis options")
        self.choice: int | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("From which step do you want to start your analysis?")
        )

        for label, value in [
            ("Logs file", self.LOGS),
            ("Original CSV file", self.ORIGINAL_CSV),
            ("Computed CSV file", self.COMPUTED_CSV),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, v=value: self._select(v))
            layout.addWidget(btn)

    def _select(self, value: int) -> None:
        self.choice = value
        self.accept()


if __name__ == "__main__":

    app = QApplication(sys.argv)

    # Ask which analysis to run
    # ----------------
    dialog = AnalysisOptionDialog()
    exit = False
    if not dialog.exec():
        sys.exit(0)

    option = dialog.choice
    print("option:", option)
    if option is None:
        QMessageBox.warning(
            None,
            "Bug in option selection",
            (
                "A bug occurred in the option selection dialog. "
                "Please try again or contact support."
            ),
        )
        sys.exit(0)

    if option <= AnalysisOptionDialog.LOGS:
        # Load and merge logs
        # ----------------
        log_files = select_files(".log.txt")
        merged_file = merge_logs(log_files)
        # merged_file = (
        #     Path.home()
        #     / "Syncnot"
        #     / "micecraft"
        #     / "src"
        #     / "micecraft"
        #     / "examples"
        #     / "experiments"
        #     / "visualdiscrimination"
        #     / "data"
        #     / "merged"
        #     / "modif_visual_discrimination_example-2026-merged.log.txt"
        # )

        # Create csv files
        # ----------------
        if merged_file is not None:
            extractor = LogAnalyzer(merged_file)
            extractor.process_log()
            sensors_path, sessions_path, trials_path = extractor.to_csv()

    else:
        # Load csv files
        # ----------------
        csv_files = select_files(".csv")
        sensors_path, sessions_path, trials_path = None, None, None

        for f in csv_files:
            if f.name.endswith(".sensors.csv"):
                sensors_path = f
            if f.name.endswith(".sessions.csv"):
                sessions_path = f
            if f.name.endswith(".trials.csv"):
                trials_path = f

        if not all([sensors_path, sessions_path, trials_path]):
            QMessageBox.warning(
                None,
                "Missing CSV files",
                (
                    "Please select all three CSV files (sensors, sessions and "
                    "trials) to run the analysis from CSV files."
                ),
            )
            sys.exit(0)

    if option <= AnalysisOptionDialog.ORIGINAL_CSV:
        # TODO
        pass

    if option <= AnalysisOptionDialog.COMPUTED_CSV:
        # TODO
        pass

# C:\Users\xavie\Syncnot\micecraft\src\micecraft\examples\experiments\visualdiscrimination\data\merged

