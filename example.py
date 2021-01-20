
"""
Basic usage of PPK2 Python API.
The basic ampere mode sequence is:
1. read modifiers
2. set ampere mode
3. read stream of data
"""
import time
from src.ppk2_api import PPK2_API
from threading import Thread

ppk2s_connected = PPK2_API.list_devices()
if(len(ppk2s_connected) == 1):
    ppk2_port = ppk2s_connected[0]
    print(f'Found PPK2 at {ppk2_port}')
else:
    print(f'Too many connected PPK2\'s: {ppk2s_connected}')
    exit()

ppk2 = PPK2_API(ppk2_port)
ppk2.get_modifiers()
ppk2.use_source_meter()
ppk2.set_source_voltage(3000)
ppk2.toggle_DUT_power("OFF")  # disable DUT power

ppk2.start_measuring()  # start measuring
# measurements are a constant stream of bytes
# the number of measurements in one sampling period depends on the wait between serial reads
# it appears the maximum number of bytes received is 1024
# the sampling rate of the PPK2 is 100 samples per millisecond

# setup wall clock
samples = 0
sampling_time = 3*60
def print_seconds(sampling_time):
    t = 0
    while(t < sampling_time +1):
        print(f'Seconds elapsed:{t}')
        try:
            print(f"Average of {len(samples)} samples is: {sum(samples)/len(samples)}uA")
        except:
            pass
        t += 1
        time.sleep(1)

process = Thread(target=print_seconds, args=[sampling_time])
process.start()
for i in range(0, 50):
    read_data = ppk2.get_data()
    if read_data != b'':
        samples = ppk2.get_samples(read_data)
        #print(f"Average of {len(samples)} samples is: {sum(samples)/len(samples)}uA")
    time.sleep(0.01)

ppk2.toggle_DUT_power("ON")
print('Power toggled')
ppk2.start_measuring()
timeout_start = time.time()
while(time.time() < (timeout_start + sampling_time)):
    read_data = ppk2.get_data()
    if read_data != b'':
        samples = ppk2.get_samples(read_data)
        # print(f"Average of {len(samples)} samples is: {sum(samples)/len(samples)}uA")
    time.sleep(0.001)  # lower time between sampling -> less samples read in one sampling period

ppk2.stop_measuring()