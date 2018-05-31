#!/usr/bin/env python

import rospy, serial, math
from sensor_msgs.msg import LaserScan
import oculusprimesocket
import thread


turning = False
READINTERVAL = 0.0014

def cleanup():
	ser.write("p\n") # stop lidar rotation
	ser.write("n\n") # disable broadcast
	ser.write("0\n") # disable lidar
	ser.close()
	rospy.sleep(3)
	print("lidar disabled, shutdown");
	oculusprimesocket.sendString("state lidar false")
	
def directionListenerThread():
	global turning
	while oculusprimesocket.connected:
		s = oculusprimesocket.waitForReplySearch("<state> direction")
		direction = s.split()[2]
		if direction == "left" or direction == "right":
			turning = True
		else:
			turning = False
			
def checkBoardId():
	ser.write("x\n") # check board id
	line = ""
	rospy.sleep(0.1)
	while ser.inWaiting() > 0:
		line = ser.readline().strip()
		print(line)

	if not line == "<id::xaxxonlidar>":
		rospy.signal_shutdown("incorrect board id")
		print("incorrect board id")
		return False
	
	return True

# main

dropscan = False
scannum = 0

rospy.init_node('xaxxon_lidar', anonymous=False)
rospy.on_shutdown(cleanup)
scan_pub = rospy.Publisher('scan', LaserScan, queue_size=3)

oculusprimesocket.connect()
thread.start_new_thread( directionListenerThread, () )
oculusprimesocket.sendString("state lidar true")

# usb connect
portnum = 0;

while portnum <= 6:
	port = '/dev/ttyUSB'+str(portnum)
	print("trying port: "+port)
	
	try: 
		ser = serial.Serial(port, 115200,timeout=10)
	except serial.SerialException: 
		portnum += 1
		rospy.sleep(1)
		continue
		
	rospy.sleep(2)

	if checkBoardId():
		break
		
	ser.close()
	rospy.sleep(1)
	portnum += 1


ser.write("y\n") # get version
line = ""
rospy.sleep(0.1)
while ser.inWaiting() > 0:
	line = ser.readline().strip()
	print(line)

""" alternate speed option: """
# ser.write("r")
# ser.write(chr(120)) # 255 max - also max rated rpm is 300, 250 safer
# ser.write("\n")

# start lidar	
ser.write("g\n") # start rotation, full speed
ser.write("1\n") # enable lidar
ser.write("b\n") # enable broadcast

# clear buffer
ser.reset_input_buffer()

raw_data = []
lastscan = rospy.Time.now()
headercodesize = 4
current_time = 0

while not rospy.is_shutdown() and ser.is_open:
	
	# read data and dump into array, checking for header code 0xFF,0xFF,0xFF,0xFF
	ch = ser.read(1)
	
	if len(ch) == 0:
		rospy.logerr("no response from xaxxonlidar device")
		break
	
	raw_data.append(ch)
	
	if turning:
		dropscan = True
			
	if not ord(ch) == 0xFF:
		continue
	else:
		ch = ser.read(1)
		raw_data.append(ch)
		if not ord(ch) == 0xFF:
			continue
		else: 
			ch = ser.read(1)
			raw_data.append(ch)
			if not ord(ch) == 0xFF:
				continue
			else: 
				ch = ser.read(1)
				raw_data.append(ch)
				if not ord(ch) == 0xFF:
					continue

	ser.write("h\n") # send host hearbeat (every <10 sec minimum)

	# read count		
	low = ord(ser.read(1))
	high = ord(ser.read(1))
	count = (high<<8)|low

	# """ read first distance offset """
	# low = ord(ser.read(1))
	# high = ord(ser.read(1))
	# firstDistanceOffset = ((high<<8)|low)/1000000.0
	
	""" read cycle """
	c1 = ord(ser.read(1))
	c2 = ord(ser.read(1))
	c3 = ord(ser.read(1))
	c4 = ord(ser.read(1))
	cycle = ((c4<<24)|(c3<<16)|(c2<<8)|c1)/1000000.0
	
	# """ read last distance offset """
	# low = ord(ser.read(1))
	# high = ord(ser.read(1))
	# lastDistanceOffset = ((high<<8)|low)/1000000.0
		
	if current_time == 0:
		current_time = rospy.Time.now() # - rospy.Duration(0.0) #0.015
	else:
		current_time += rospy.Duration(cycle)
	rospycycle = current_time - lastscan
	# cycle = rospycycle.to_sec()
	lastscan = current_time
	
	rospycount = (len(raw_data)-headercodesize)/2
	
	
	if not count == 0:
		print "cycle: "+str(cycle)
		## print "rospycycle: "+str(rospycycle.to_sec())
		print "count: "+str(count)
		# print "lastDistanceOffset: "+str(lastDistanceOffset)
		## print "firstDistanceOffset: "+str(firstDistanceOffset)
		print "scannum: "+str(scannum)
		# print "interval: "+str(cycle/count)
		## print "raw_data length: "+str((len(raw_data)-headercodesize)/2)
	if not rospycount == count:
		print "*** COUNT/DATA MISMATCH *** "+ str( rospycount-count )
	print " "

	
	scannum += 1	
	if scannum <= 5: # drop 1st few scans while lidar spins up
		del raw_data[:]
		continue
	
	scan = LaserScan()
	scan.header.stamp = current_time - rospycycle # - rospy.Duration(0.01) #rospy.Duration(cycle) 
	scan.header.frame_id = 'laser_frame'

	scan.angle_min = 0
	#  scan.angle_max = (2 * math.pi) 

	# scan.angle_min = (firstDistanceOffset/cycle) * (2 * math.pi)
	# scan.angle_max = (2 * math.pi) - ((lastDistanceOffset/cycle)  * (2 * math.pi))
	
	# scan.angle_increment = READINTERVAL / cycle * 2 * math.pi
	# scan.angle_max = scan.angle_increment * (count-1)
	
	scan.angle_max = (cycle - READINTERVAL*3)/cycle * 2 * math.pi
	# scan.angle_max = (cycle - lastDistanceOffset)/cycle * 2 * math.pi
	scan.angle_increment = scan.angle_max / (count-1)

	#  scan.angle_increment = 2 * math.pi / count
	# scan.angle_increment = (scan.angle_max - scan.angle_min) / (count-1)
	scan.time_increment =  cycle/count
	scan.scan_time = cycle # rospycycle.to_sec()
	scan.range_min = 0.05
	scan.range_max = 20.0

	temp = []
	for x in range(len(raw_data)-(count*2)-headercodesize, len(raw_data)-headercodesize, 2):
		low = ord(raw_data[x])
		high = ord(raw_data[x+1])
		value = ((high<<8)|low) / 100.0
		if value < 0.4:
			value = 0
		temp.append(value)

	# comp rpm photo sensor offset
	tilt = 280 # degrees
	split = int(tilt/360.0*count)
	scan.ranges = temp[split:]+temp[0:split]

	# #masking frame
	maskwidth = 6 # half width, degrees
	masks = [92,133, 270, 315]
	for m in masks:
		for x in range(int(count*((m-maskwidth)/360.0)), int(count*((m+maskwidth)/360.0)) ):
			scan.ranges[x] = 0
			
	if dropscan: 	# blank scans when turning
		for i in range(len(scan.ranges)):
			scan.ranges[i] = 0
	dropscan = False
		
	scan_pub.publish(scan)
	
	del raw_data[:] 

	# if scannum % 10 == 0:
		# msg = "scan #: "+str(scannum)
		# rospy.loginfo(msg)

