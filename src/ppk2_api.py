"""
This python API is written for use with the Nordic Semiconductor's Power Profiler Kit II (PPK 2).
The PPK2 uses Serial communication.
The official nRF Connect Power Profiler was used as a reference: https://github.com/NordicSemiconductor/pc-nrfconnect-ppk
"""

import serial
import time
import struct


class PPK2_Command():
    """Serial command opcodes"""
    NO_OP = 0x00
    TRIGGER_SET = 0x01
    AVG_NUM_SET = 0x02  # no-firmware
    TRIGGER_WINDOW_SET = 0x03
    TRIGGER_INTERVAL_SET = 0x04
    TRIGGER_SINGLE_SET = 0x05
    AVERAGE_START = 0x06
    AVERAGE_STOP = 0x07
    RANGE_SET = 0x08
    LCD_SET = 0x09
    TRIGGER_STOP = 0x0a
    DEVICE_RUNNING_SET = 0x0c
    REGULATOR_SET = 0x0d
    SWITCH_POINT_DOWN = 0x0e
    SWITCH_POINT_UP = 0x0f
    TRIGGER_EXT_TOGGLE = 0x11
    SET_POWER_MODE = 0x11
    RES_USER_SET = 0x12
    SPIKE_FILTERING_ON = 0x15
    SPIKE_FILTERING_OFF = 0x16
    GET_META_DATA = 0x19
    RESET = 0x20
    SET_USER_GAINS = 0x25

class PPK2_Modes():
    """PPK2 measurement modes"""
    AMPERE_MODE = "AMPERE_MODE"
    SOURCE_MODE = "SOURCE_MODE"

class PPK2_API():
    def __init__(self, port):

        self.ser = serial.Serial(port)
        self.ser.baudrate = 9600

        self.modifiers = {
            "Calibrated": None,
            "R": {"0": None, "1": None, "2": None, "3": None, "4": None},
            "GS": {"0": None, "1": None, "2": None, "3": None, "4": None},
            "GI": {"0": None, "1": None, "2": None, "3": None, "4": None},
            "O": {"0": None, "1": None, "2": None, "3": None, "4": None},
            "S": {"0": None, "1": None, "2": None, "3": None, "4": None},
            "I": {"0": None, "1": None, "2": None, "3": None, "4": None},
            "UG": {"0": None, "1": None, "2": None, "3": None, "4": None},
            "HW": None,
            "IA": None
        }

        self.vdd_low = 800
        self.vdd_high = 5000

        self.current_vdd = 0

        self.adc_mult = 1.8 / 163840

        self.MEAS_ADC = self._generate_mask(14, 0)
        self.MEAS_RANGE = self._generate_mask(3, 14)
        self.MEAS_LOGIC = self._generate_mask(8, 24)

        self.prev_rolling_avg = None
        self.prev_rolling_avg4 = None
        self.prev_range = None

        self.mode = None

        # adc measurement buffer remainder and len of remainder
        self.remainder = {"sequence": b'', "len": 0}

    def _pack_struct(self, cmd_tuple):
        """Returns packed struct"""
        return struct.pack("B" * len(cmd_tuple), *cmd_tuple)

    def _write_serial(self, cmd_tuple):
        """Writes cmd bytes to serial"""
        cmd_packed = self._pack_struct(cmd_tuple)
        self.ser.write(cmd_packed)

    def _twos_comp(self, val):
        """Compute the 2's complement of int32 value"""
        if (val & (1 << (32 - 1))) != 0:
            val = val - (1 << 32)  # compute negative value
        return val

    def _convert_source_voltage(self, mV):
        """Convert input voltage to device command"""
        # minimal possible mV is 800
        if mV < self.vdd_low:
            mV = self.vdd_low

        # maximal possible mV is 5000
        if mV > self.vdd_high:
            mV = self.vdd_high

        offset = 32
        # get difference to baseline (the baseline is 800mV but the initial offset is 32)
        diff_to_baseline = mV - self.vdd_low + offset
        base_b_1 = 3
        base_b_2 = 0  # is actually 32 - compensated with above offset

        # get the number of times we have to increase the first byte of the command
        ratio = int(diff_to_baseline / 256)
        remainder = diff_to_baseline % 256  # get the remainder for byte 2

        set_b_1 = base_b_1 + ratio
        set_b_2 = base_b_2 + remainder

        return set_b_1, set_b_2

    def _read_metadata(self):
        """Read metadata"""
        # try to get metadata from device
        for _ in range(0, 5):
            # it appears the second reading is the metadata
            read = self.ser.read(self.ser.in_waiting)
            time.sleep(0.1)

            if read != b'' and "END" in read.decode("utf-8"):
                return read.decode("utf-8")

    def _parse_metadata(self, metadata):
        """Parse metadata and store it to modifiers"""
        data_split = [row.split(": ") for row in metadata.split("\n")]

        for key in self.modifiers.keys():
            for data_pair in data_split:
                if key == data_pair[0]:
                    self.modifiers[key] = data_pair[1]
                for ind in range(0, 5):
                    if key+str(ind) == data_pair[0]:
                        self.modifiers[key][str(ind)] = float(data_pair[1])

    def _generate_mask(self, bits, pos):
        pos = pos
        mask = ((2**bits-1) << pos)
        mask = self._twos_comp(mask)
        return {"mask": mask, "pos": pos}

    def _get_masked_value(self, value, meas):
        masked_value = (value & meas["mask"]) >> meas["pos"]
        return masked_value

    def _handle_raw_data(self, adc_value):
        """Convert raw value to analog value"""
        current_measurement_range = min(self._get_masked_value(
            adc_value, self.MEAS_RANGE), 5)  # 5 is the number of parameters
        adc_result = self._get_masked_value(adc_value, self.MEAS_ADC) * 4
        bits = self._get_masked_value(adc_value, self.MEAS_LOGIC)
        analog_value = self.get_adc_result(
            current_measurement_range, adc_result) * 10**6

        return analog_value

    def get_data(self):
        """Return readings of one sampling period"""
        sampling_data = self.ser.read(self.ser.in_waiting)
        return sampling_data

    def get_modifiers(self):
        """Gets and sets modifiers from device memory"""
        self._write_serial((PPK2_Command.GET_META_DATA, ))
        metadata = self._read_metadata()
        self._parse_metadata(metadata)

    def start_measuring(self):
        """Start continous measurement"""
        self._write_serial((PPK2_Command.AVERAGE_START, ))

    def stop_measuring(self):
        """Stop continous measurement"""
        self._write_serial((PPK2_Command.AVERAGE_STOP, ))

    def set_source_voltage(self, mV):
        """Inits device - based on observation only REGULATOR_SET is the command. 
        The other two values correspond to the voltage level.

        800mV is the lowest setting - [3,32] - the values then increase linearly
        """
        b_1, b_2 = self._convert_source_voltage(mV)
        self._write_serial((PPK2_Command.REGULATOR_SET, b_1, b_2))
        #self.current_vdd = mV

    def toggle_DUT_power(self, state):
        """Toggle DUT power based on parameter"""
        if state == "ON":
            self._write_serial((PPK2_Command.DEVICE_RUNNING_SET, PPK2_Command.TRIGGER_SET))  # 12,1

        if state == "OFF":
            self._write_serial((PPK2_Command.DEVICE_RUNNING_SET, PPK2_Command.NO_OP))  # 12,0

    def use_ampere_meter(self):
        """Configure device to use ampere meter"""
        self.mode = PPK2_Modes.AMPERE_MODE
        self._write_serial((PPK2_Command.SET_POWER_MODE, PPK2_Command.TRIGGER_SET))  # 17,1

    def use_source_meter(self):
        """Configure device to use source meter"""
        self.mode = PPK2_Modes.SOURCE_MODE
        self._write_serial((PPK2_Command.SET_POWER_MODE, PPK2_Command.AVG_NUM_SET))  # 17,2

    def get_adc_result(self, current_range, adc_value):
        """Get result of adc conversion"""
        current_range = str(current_range)
        result_without_gain = (adc_value - self.modifiers["O"][current_range]) * (
            self.adc_mult / self.modifiers["R"][current_range])

        adc = self.modifiers["UG"][current_range] * (
            result_without_gain *
            (self.modifiers["GS"][current_range] *
             result_without_gain + self.modifiers["GI"][current_range])
             # this part is used only in source meter mode
            + (self.modifiers["S"][current_range] + 
               (self.current_vdd / 1000) + self.modifiers["I"][current_range])
        )

        self.rolling_avg = adc
        self.rolling_avg4 = adc

        return adc

    def _digital_to_analog(self, adc_value):
        """Convert discrete value to analog value"""
        return int.from_bytes(adc_value, byteorder="little", signed=False)  # convert reading to analog value

    def average_of_sampling_period(self, buf):
        """
        Calculates the average value of one sampling period.
        The number of sampled values depends on the delay between serial reads.
        See example for more info.
        """

        sample_size = 4  # one analog value is 4 bytes in size
        offset = self.remainder["len"]
        measurement_avg = 0
        num_samples = 0

        first_reading = (self.remainder["sequence"] + buf[0:sample_size-offset])[:4]
        adc_val = self._digital_to_analog(first_reading)
        measurement_avg += self._handle_raw_data(adc_val)
        num_samples += 1

        offset = sample_size - offset

        while offset <= len(buf) - sample_size:
            next_val = buf[offset:offset + sample_size]
            offset += sample_size
            adc_val = self._digital_to_analog(next_val)

            measurement_avg += self._handle_raw_data(adc_val)
            num_samples += 1

        print("Avg of {} samples: {} μA".format(
            num_samples, measurement_avg/num_samples))

        self.remainder["sequence"] = buf[offset:len(buf)]
        self.remainder["len"] = len(buf)-offset

        return measurement_avg/num_samples