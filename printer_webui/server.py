# coding=utf-8
__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'

from flask import Flask, request, render_template, jsonify, send_from_directory, abort, url_for
from werkzeug import secure_filename
import tornadio2

import os
import fnmatch
import datetime

from printer_webui.printer import Printer, getConnectionOptions, PrinterCallback
from printer_webui.settings import settings
import printer_webui.timelapse as timelapse

BASEURL = "/ajax/"
SUCCESS = {}

UPLOAD_FOLDER = settings().getBaseFolder("uploads")

app = Flask("printer_webui")
printer = Printer()

@app.route("/")
def index():
	return render_template(
		"index.html",
		webcamStream=settings().get("webcam", "stream"),
		enableTimelapse=(settings().get("webcam", "snapshot") is not None and settings().get("webcam", "ffmpeg") is not None)
	)

#~~ Printer state

class PrinterStateConnection(tornadio2.SocketConnection, PrinterCallback):
	def on_open(self, info):
		print("Opened socket")
		printer.registerCallback(self)

	def on_close(self):
		print("Closed socket")
		printer.unregisterCallback(self)

	def zChangeCB(self, currentZ):
		formattedCurrentZ = None
		if currentZ:
			formattedCurrentZ = "%.2f mm" % (currentZ)

		print("Sending zChange...")
		self.emit("zChange", {"currentZ": formattedCurrentZ})

	def progressChangeCB(self, currentLine, printTimeInSeconds, printTimeLeftInMinutes):
		formattedPrintTime = None
		if (printTimeInSeconds):
			formattedPrintTime = _getFormattedTimeDelta(datetime.timedelta(seconds=printTimeInSeconds))

		formattedPrintTimeLeft = None
		if (printTimeLeftInMinutes):
			formattedPrintTimeLeft = _getFormattedTimeDelta(datetime.timedelta(minutes=printTimeLeftInMinutes))

		print("Sending progressChange...")
		self.emit("printProgress", {
			"currentLine": currentLine,
			"printTime": formattedPrintTime,
			"printTimeLeft": formattedPrintTimeLeft
		})

	def temperatureChangeCB(self, currentTime, temp, bedTemp, targetTemp, targetBedTemp):
		print("Sending temperatureChange...")
		self.emit("temperature", {
			"currentTime": currentTime,
			"temp": temp,
			"bedTemp": bedTemp,
			"targetTemp": targetTemp,
			"targetBedTemp": targetBedTemp
		})

	def stateChangeCB(self, state, stateString, booleanStates):
		print("Sending stateChange...")
		self.emit("state", {"currentState": stateString, "flags": booleanStates})

	def logChangeCB(self, line):
		print("Sending logChange...")
		self.emit("log", {"line": line})

	def messageChangeCB(self, line):
		print("Sending messageChange...")
		self.emit("message", {"line": line})

	def gcodeChangeCB(self, filename, progress):
		print("Sending gcodeChange...")
		self.emit("jobData", {"filename": "Loading... (%d%%)" % (round(progress * 100)), "lineCount": None, "estimatedPrintTime": None, "filament": None})

	def jobDataChangeCB(self, filename, lines, estimatedPrintTimeInMinutes, filamentLengthInMillimeters):
		formattedPrintTimeEstimation = None
		if estimatedPrintTimeInMinutes:
			formattedPrintTimeEstimation = _getFormattedTimeDelta(datetime.timedelta(minutes=estimatedPrintTimeInMinutes))

		formattedFilament = None
		if filamentLengthInMillimeters:
			formattedFilament = "%.2fm" % (filamentLengthInMillimeters / 1000)

		formattedFilename = None
		if filename:
			formattedFilename = filename.replace(UPLOAD_FOLDER + os.sep, "")

		print("Sending jobDataChange...")
		self.emit("jobData", {"filename": formattedFilename, "lineCount": lines, "estimatedPrintTime": formattedPrintTimeEstimation, "filament": formattedFilament})

	def sendHistoryData(self, tempHistory, logHistory, messageHistory):
		print("Sending history...")
		self.emit("history", {"temperature": tempHistory, "log": logHistory, "message": messageHistory})

#~~ Printer control

@app.route(BASEURL + "control/connectionOptions", methods=["GET"])
def connectionOptions():
	return jsonify(getConnectionOptions())

@app.route(BASEURL + "control/connect", methods=["POST"])
def connect():
	port = None
	baudrate = None
	if request.values.has_key("port"):
		port = request.values["port"]
	if request.values.has_key("baudrate"):
		baudrate = request.values["baudrate"]
	if request.values.has_key("save"):
		settings().set("serial", "port", port)
		settings().set("serial", "baudrate", baudrate)
		settings().save()
	printer.connect(port=port, baudrate=baudrate)
	return jsonify(state="Connecting")

@app.route(BASEURL + "control/disconnect", methods=["POST"])
def disconnect():
	printer.disconnect()
	return jsonify(state="Offline")

@app.route(BASEURL + "control/command", methods=["POST"])
def printerCommand():
	command = request.form["command"]
	printer.command(command)
	return jsonify(SUCCESS)

@app.route(BASEURL + "control/print", methods=["POST"])
def printGcode():
	printer.startPrint()
	return jsonify(SUCCESS)

@app.route(BASEURL + "control/pause", methods=["POST"])
def pausePrint():
	printer.togglePausePrint()
	return jsonify(SUCCESS)

@app.route(BASEURL + "control/cancel", methods=["POST"])
def cancelPrint():
	printer.cancelPrint()
	return jsonify(SUCCESS)

@app.route(BASEURL + "control/temperature", methods=["POST"])
def setTargetTemperature():
	if not printer.isOperational():
		return jsonify(SUCCESS)

	if request.values.has_key("temp"):
		# set target temperature
		temp = request.values["temp"];
		printer.command("M104 S" + temp)

	if request.values.has_key("bedTemp"):
		# set target bed temperature
		bedTemp = request.values["bedTemp"]
		printer.command("M140 S" + bedTemp)

	return jsonify(SUCCESS)

@app.route(BASEURL + "control/jog", methods=["POST"])
def jog():
	if not printer.isOperational() or printer.isPrinting():
		# do not jog when a print job is running or we don"t have a connection
		return jsonify(SUCCESS)

	if request.values.has_key("x"):
		# jog x
		x = request.values["x"]
		printer.commands(["G91", "G1 X" + x + " F6000", "G90"])
	if request.values.has_key("y"):
		# jog y
		y = request.values["y"]
		printer.commands(["G91", "G1 Y" + y + " F6000", "G90"])
	if request.values.has_key("z"):
		# jog z
		z = request.values["z"]
		printer.commands(["G91", "G1 Z" + z + " F200", "G90"])
	if request.values.has_key("homeXY"):
		# home x/y
		printer.command("G28 X0 Y0")
	if request.values.has_key("homeZ"):
		# home z
		printer.command("G28 Z0")

	return jsonify(SUCCESS)

@app.route(BASEURL + "control/speed", methods=["POST"])
def speed():
	if not printer.isOperational():
		return jsonify(SUCCESS)

	for key in ["outerWall", "innerWall", "fill", "support"]:
		if request.values.has_key(key):
			value = int(request.values[key])
			printer.setFeedrateModifier(key, value)

	return jsonify(feedrate = printer.feedrateState())

#~~ GCODE file handling

@app.route(BASEURL + "gcodefiles", methods=["GET"])
def readGcodeFiles():
	files = []
	for osFile in os.listdir(UPLOAD_FOLDER):
		if not fnmatch.fnmatch(osFile, "*.gcode"):
			continue
		files.append({
			"name": osFile,
			"size": sizeof_fmt(os.stat(os.path.join(UPLOAD_FOLDER, osFile)).st_size)
		})
	return jsonify(files=files)

@app.route(BASEURL + "gcodefiles/upload", methods=["POST"])
def uploadGcodeFile():
	if request.files.has_key("gcode_file"):
		file = request.files["gcode_file"]
		if file and allowed_file(file.filename, set(["gcode"])):
			secure = secure_filename(file.filename)
			filename = os.path.join(UPLOAD_FOLDER, secure)
			file.save(filename)
	return readGcodeFiles()

@app.route(BASEURL + "gcodefiles/load", methods=["POST"])
def loadGcodeFile():
	if request.values.has_key("filename"):
		filename = request.values["filename"]
		printer.loadGcode(os.path.join(UPLOAD_FOLDER, filename))
	return jsonify(SUCCESS)

@app.route(BASEURL + "gcodefiles/delete", methods=["POST"])
def deleteGcodeFile():
	if request.values.has_key("filename"):
		filename = request.values["filename"]
		if allowed_file(filename, set(["gcode"])):
			secure = os.path.join(UPLOAD_FOLDER, secure_filename(filename))
			if os.path.exists(secure):
				os.remove(secure)
	return readGcodeFiles()

#~~ timelapse handling

@app.route(BASEURL + "timelapse", methods=["GET"])
def getTimelapseData():
	lapse = printer.getTimelapse()

	type = "off"
	additionalConfig = {}
	if lapse is not None and isinstance(lapse, timelapse.ZTimelapse):
		type = "zchange"
	elif lapse is not None and isinstance(lapse, timelapse.TimedTimelapse):
		type = "timed"
		additionalConfig = {
			"interval": lapse.interval
		}

	files = timelapse.getFinishedTimelapses()
	for file in files:
		file["size"] = sizeof_fmt(file["size"])
		file["url"] = url_for("downloadTimelapse", filename=file["name"])

	return jsonify({
	"type": type,
	"config": additionalConfig,
	"files": files
	})

@app.route(BASEURL + "timelapse/<filename>", methods=["GET"])
def downloadTimelapse(filename):
	if allowed_file(filename, set(["mpg"])):
		return send_from_directory(settings().getBaseFolder("timelapse"), filename, as_attachment=True)

@app.route(BASEURL + "timelapse/<filename>", methods=["DELETE"])
def deleteTimelapse(filename):
	if allowed_file(filename, set(["mpg"])):
		secure = os.path.join(settings().getBaseFolder("timelapse"), secure_filename(filename))
		if os.path.exists(secure):
			os.remove(secure)
	return getTimelapseData()

@app.route(BASEURL + "timelapse/config", methods=["POST"])
def setTimelapseConfig():
	if request.values.has_key("type"):
		type = request.values["type"]
		lapse = None
		if "zchange" == type:
			lapse = timelapse.ZTimelapse()
		elif "timed" == type:
			interval = 10
			if request.values.has_key("interval"):
				try:
					interval = int(request.values["interval"])
				except ValueError:
					pass
			lapse = timelapse.TimedTimelapse(interval)
		printer.setTimelapse(lapse)

	return getTimelapseData()

#~~ settings

@app.route(BASEURL + "settings", methods=["GET"])
def getSettings():
	s = settings()
	return jsonify({
		"serial_port": s.get("serial", "port"),
		"serial_baudrate": s.get("serial", "baudrate")
	})

@app.route(BASEURL + "settings", methods=["POST"])
def setSettings():
	s = settings()
	if request.values.has_key("serial_port"):
		s.set("serial", "port", request.values["serial_port"])
	if request.values.has_key("serial_baudrate"):
		s.set("serial", "baudrate", request.values["serial_baudrate"])

	s.save()
	return getSettings()

#~~ helper functions

def _getFormattedTimeDelta(d):
	hours = d.seconds // 3600
	minutes = (d.seconds % 3600) // 60
	seconds = d.seconds % 60
	return "%02d:%02d:%02d" % (hours, minutes, seconds)

def sizeof_fmt(num):
	"""
	 Taken from http://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
	"""
	for x in ["bytes","KB","MB","GB"]:
		if num < 1024.0:
			return "%3.1f%s" % (num, x)
		num /= 1024.0
	return "%3.1f%s" % (num, "TB")

def allowed_file(filename, extensions):
	return "." in filename and filename.rsplit(".", 1)[1] in extensions

#~~ startup code

def run(host = "0.0.0.0", port = 5000, debug = False):
	from tornado.wsgi import WSGIContainer
	from tornado.httpserver import HTTPServer
	from tornado.ioloop import IOLoop
	from tornado.web import Application, FallbackHandler

	print "Listening on http://%s:%d" % (host, port)
	app.debug = debug

	router = tornadio2.TornadioRouter(PrinterStateConnection)
	tornado_app = Application(router.urls + [
		(".*", FallbackHandler, {"fallback": WSGIContainer(app)})
	])
	server = HTTPServer(tornado_app)
	server.listen(port, address=host)
	IOLoop.instance().start()

def main():
	from optparse import OptionParser

	defaultHost = settings().get("server", "host")
	defaultPort = settings().get("server", "port")

	parser = OptionParser(usage="usage: %prog [options]")
	parser.add_option("-d", "--debug", action="store_true", dest="debug",
		help="Enable debug mode")
	parser.add_option("--host", action="store", type="string", default=defaultHost, dest="host",
		help="Specify the host on which to bind the server, defaults to %s if not set" % (defaultHost))
	parser.add_option("--port", action="store", type="int", default=defaultPort, dest="port",
		help="Specify the port on which to bind the server, defaults to %s if not set" % (defaultPort))
	(options, args) = parser.parse_args()

	run(host=options.host, port=options.port, debug=options.debug)

if __name__ == "__main__":
	main()