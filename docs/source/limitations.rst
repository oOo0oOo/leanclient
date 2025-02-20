Limitations of the LSP
======================

Limited interface made for humans
---------------------------------

The LSP only allows for a few requests, many require post-processing to be useful (e.g. the highlight range).
Extending the LSP is possible in lean4 user space but not easy (see this `discussion on zulip <https://leanprover.zulipchat.com/#narrow/channel/270676-lean4/topic/User.20defined.20LSP.20extensions>`_).


New parametrization: Line, character
------------------------------------

Usually the user provides these parameters. You will have to write a program that does this.
If you change/update files using the LSP, you are additionally responsible for all white space and indentation.
Bonus: If the LSP does not provide the position you need, you start parsing files manually...


Slow to open files
------------------

Opening time for a file is the same as in the lean4 vscode extension (yellow bar). Subsequent updates are typically faster.


Verify LSP response
-------------------

Verify the output of the LSP if possible, specially for methods labelled as "experimental".
If you find any issues, please let me know!
