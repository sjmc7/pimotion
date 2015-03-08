import optparse
import datetime
import io
import itertools
import os
import time
import numpy
import picamera
import picamera.array

resolution = (800, 600)

usage = "usage: %prog [options] output_filename"
parser = optparse.OptionParser()
parser.add_option("--night", 
                  action="store_true",
                  default=True,
                  help="Low light exposure")
parser.add_option("--record-seconds",
                  default=10,
                  type=int,
                  help="Minimum recording time (recording always continues "
                       "if motion continues)")
parser.add_option("--output-filename", default="capture.h264")
parser.add_option("--resolution", default="800x600")
parser.add_option("--sensitivity", default=60, type=int,
                  help="How big a difference counts for motion detection")
parser.add_option("--difference-percentage", default=30, type=int,
                  help="How much of the frames must change to count as motion")
options, args = parser.parse_args()


try:
    os.remove(options.output_filename)
except OSError:
    pass


def log_message(msg):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("{0} {1}".format(now, msg))


class DetectMotion(picamera.array.PiMotionAnalysis):
    """From the picamera 'array' documentation. PiMotionAnalysis makes
    available 16x16 pixel blocks between frames
    """
    def __init__(self, camera):
        super(DetectMotion, self).__init__(camera)
        # This flag is only ever set, indicating motion has occurred
        # since it was last reset
        self.motion_flag = False

    def analyse(self, a):
        """a['sad'] is also available, the 'sum of all differences'.
        This builds an array representing vectors (changes) consisting
        of the root of the sum of squares
        """
        total_blocks = len(a['x'])

        a = numpy.sqrt(
            numpy.square(a['x'].astype(numpy.float)) +
            numpy.square(a['y'].astype(numpy.float))
            ).clip(0, 255).astype(numpy.uint8)

        need_to_change = (total_blocks * options.difference_percentage) / 100
        blocks_changed = (a > options.sensitivity).sum()
        if (blocks_changed > need_to_change):
            log_message("Motion detected! (%d blocks)" % blocks_changed)
            self.motion_flag = True


def timestamp():
    return datetime.datetime.now().strftime("%H:%M:%S")

def record_until_inactive(camera, motion_analysis):
    while motion_analysis.motion_flag:
        motion_analysis.motion_flag = False
        for _ in xrange(options.record_seconds * 2):
            camera.annotate_text = timestamp()
            camera.wait_recording(0.5)
        if motion_analysis.motion_flag:
            log_message("Further motion detected; continuing recording") 

    log_message("Finished recording; continue monitoring")
    camera.annotate_text = timestamp() + " (going idle)"


with picamera.PiCamera() as camera:
    # To record before an event, write to a circular buffer
    #idle_stream = picamera.PiCameraCircularIO(camera, seconds=10)
    # ... or chuck it away
    idle_stream = '/dev/null'

    with DetectMotion(camera) as motion_analysis:
        camera.resolution = map(int, options.resolution.split('x'))
        camera.framerate = 15
        if options.night:
            camera.exposure_mode = "night"

        camera.start_recording(idle_stream,
            format='h264', motion_output=motion_analysis)

        try:
            log_message("Starting recording at %s,%s" % resolution)

            while True:
                camera.wait_recording(1)
                if motion_analysis.motion_flag:
                    log_message("Recording next %d seconds to %s" %
                                (options.record_seconds,
                                 options.output_filename))

                    with io.open(options.output_filename, 'ab') as out_file:
                        # Start writing to out_file at the next SPS header,
                        # which can take several seconds
                        camera.split_recording(out_file)

                        # Record either for options.record_seconds, OR while
                        # motion is still detected
                        record_until_inactive(camera, motion_analysis)

                        # Switch back; again, this can take several seconds
                        # to take effect while waiting for an SPS header
                        camera.split_recording(idle_stream)
        finally:
            log_message("Stopping; output in %s" % options.output_filename)
            # stop_recording is important or the GPU can leak memory
            camera.stop_recording()
