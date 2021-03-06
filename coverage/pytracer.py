"""Raw data collector for Coverage."""

import sys


class PyTracer(object):
    """Python implementation of the raw data tracer."""

    # Because of poor implementations of trace-function-manipulating tools,
    # the Python trace function must be kept very simple.  In particular, there
    # must be only one function ever set as the trace function, both through
    # sys.settrace, and as the return value from the trace function.  Put
    # another way, the trace function must always return itself.  It cannot
    # swap in other functions, or return None to avoid tracing a particular
    # frame.
    #
    # The trace manipulator that introduced this restriction is DecoratorTools,
    # which sets a trace function, and then later restores the pre-existing one
    # by calling sys.settrace with a function it found in the current frame.
    #
    # Systems that use DecoratorTools (or similar trace manipulations) must use
    # PyTracer to get accurate results.  The command-line --timid argument is
    # used to force the use of this tracer.

    def __init__(self):
        # Attributes set from the collector:
        self.data = None
        self.arcs = False
        self.should_trace = None
        self.should_trace_cache = None
        self.check_include = None
        self.warn = None
        self.plugin_data = None
        # The threading module to use, if any.
        self.threading = None

        self.file_tracer = []
        self.cur_file_dict = []
        self.last_line = [0]

        self.data_stack = []
        self.last_exc_back = None
        self.last_exc_firstlineno = 0
        self.thread = None
        self.stopped = False

    def __repr__(self):
        return "<PyTracer at 0x{0:0x}: {1} lines in {2} files>".format(
            id(self),
            sum(len(v) for v in self.data.values()),
            len(self.data),
        )

    def _trace(self, frame, event, arg_unused):
        """The trace function passed to sys.settrace."""

        if self.stopped:
            return

        if self.last_exc_back:            # TODO: bring this up to speed
            if frame == self.last_exc_back:
                # Someone forgot a return event.
                if self.arcs and self.cur_file_dict:
                    pair = (self.last_line, -self.last_exc_firstlineno)
                    self.cur_file_dict[pair] = None
                self.file_tracer, self.cur_file_dict, self.last_line = (
                    self.data_stack.pop()
                )
            self.last_exc_back = None

        if event == 'call':
            # Entering a new function context.  Decide if we should trace
            # in this file.
            self.data_stack.append(
                (self.file_tracer, self.cur_file_dict, self.last_line)
            )
            filename = frame.f_code.co_filename
            disp = self.should_trace_cache.get(filename)
            if disp is None:
                disp = self.should_trace(filename, frame)
                self.should_trace_cache[filename] = disp

            self.file_tracer = None
            self.cur_file_dict = None
            if disp.trace:
                tracename = disp.source_filename
                if disp.file_tracer and disp.has_dynamic_filename:
                    tracename = disp.file_tracer.dynamic_source_filename(tracename, frame)
                    if tracename:
                        included = self.should_trace_cache.get(tracename)
                        if included is None:
                            included = self.check_include(tracename, frame)
                            self.should_trace_cache[tracename] = included
                        if not included:
                            tracename = None
            else:
                tracename = None
            if tracename:
                if tracename not in self.data:
                    self.data[tracename] = {}
                    if disp.file_tracer:
                        self.plugin_data[tracename] = disp.file_tracer.plugin_name
                self.cur_file_dict = self.data[tracename]
                self.file_tracer = disp.file_tracer
            # Set the last_line to -1 because the next arc will be entering a
            # code block, indicated by (-1, n).
            self.last_line = -1
        elif event == 'line':
            # Record an executed line.
            if self.cur_file_dict is not None:
                if self.file_tracer:
                    lineno_from, lineno_to = self.file_tracer.line_number_range(frame)
                else:
                    lineno_from, lineno_to = frame.f_lineno, frame.f_lineno
                if lineno_from != -1:
                    if self.arcs:
                        self.cur_file_dict[
                            (self.last_line, lineno_from)
                        ] = None
                    else:
                        for lineno in range(lineno_from, lineno_to+1):
                            self.cur_file_dict[lineno] = None
                self.last_line = lineno_to
        elif event == 'return':
            if self.arcs and self.cur_file_dict:
                first = frame.f_code.co_firstlineno
                self.cur_file_dict[(self.last_line, -first)] = None
            # Leaving this function, pop the filename stack.
            self.file_tracer, self.cur_file_dict, self.last_line = (
                self.data_stack.pop()
            )
        elif event == 'exception':
            self.last_exc_back = frame.f_back
            self.last_exc_firstlineno = frame.f_code.co_firstlineno
        return self._trace

    def start(self):
        """Start this Tracer.

        Return a Python function suitable for use with sys.settrace().

        """
        if self.threading:
            self.thread = self.threading.currentThread()
        sys.settrace(self._trace)
        return self._trace

    def stop(self):
        """Stop this Tracer."""
        self.stopped = True
        if self.threading and self.thread != self.threading.currentThread():
            # Called on a different thread than started us: we can't unhook
            # ourselves, but we've set the flag that we should stop, so we
            # won't do any more tracing.
            return

        if self.warn:
            if sys.gettrace() != self._trace:
                msg = "Trace function changed, measurement is likely wrong: %r"
                self.warn(msg % (sys.gettrace(),))

        sys.settrace(None)

    def get_stats(self):
        """Return a dictionary of statistics, or None."""
        return None
