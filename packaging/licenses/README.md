# Runtime license fallback

`Tcl-license.terms` is the unmodified Tcl 8.6.15 license from
https://github.com/tcltk/tcl/blob/core-8-6-15/license.terms.

Some Microsoft Store Python distributions omit this file from the Tcl library
directory. The release builder includes this copy when the installed runtime
does not supply one. Other runtime notices are collected from the installed
distributions used to build the executable.
