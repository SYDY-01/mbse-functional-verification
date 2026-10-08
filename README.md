# Automated Formal Verification with Traceability for Functional Requirements in MBSE

This repository contains the Python implementation and experimental artifacts for **Automated Formal Verification Framework with Traceability for Functional Requirements in MBSE**. It connects structured functional requirements, X-language system models, nuXmv verification, and counterexample-based traceability.

The implementation provides three stages:

1. Convert structured controlled natural language (CNL) requirements into CTL/LTL specifications, using a trace configuration and model-symbol validation.
2. Transform the supported finite, discrete subset of X-language models into nuXmv models while retaining component instance names and hierarchical identifiers.
3. Reduce counterexample traces and associate violated specifications with originating requirements, component instances, and selected model evidence.

Engineers use the resulting evidence to inspect and revise requirements or models. Revision and subsequent verification are performed by the user.

## Repository contents

| File or directory | Purpose |
| --- | --- |
| `main.py` | Entry point for X-to-nuXmv model transformation; input and output paths are configured inside `main()`. |
| `x_transpiler.py` | ANTLR frontend and typed intermediate representation, shared by model transformation and requirement binding. |
| `nuxmv_generator.py` | Generation of nuXmv modules, finite domains, state updates, timers, and event representations. |
| `CDLexer.py`, `CDParser.py`, `CDVisitor.py` | Generated X-language lexer, parser, and visitor base. |
| `REQ2CTLLTL.py` | Model-constrained CNL-to-CTL/LTL formalization, source metadata, and auxiliary trigger-reachability checks. |
| `reduce_and_trace.py` | Command-line counterexample reduction and cross-layer traceability. |
| `test_requirement_formalization.py` | Requirement-formalization regression and boundary tests. |
| `test_reduce_and_trace.py` | Self-contained traceability tests and FMCS integration regression tests. |
| `FMCS/` | Flight Mission Control System baseline inputs and saved outputs. |
| `TestWrong/` | FI-01–FI-05 fault-injected X models, verification models, logs, and reports. |
| `EventSemanticsTests/` | Event-semantics example and saved verification artifacts. |
| `TransformationConsistencyTests/` | Transformation-consistency inputs, specifications, and saved results. |

Use these canonical Python filenames without download suffixes such as `(3)` or `(4)`. Keep the parser files and implementation modules in the repository root so that local imports resolve correctly.

The CNL inputs, mapping terms, and some report text are Chinese. They are the implementation's actual inputs and outputs; this README provides English navigation and usage instructions. Preserve requirement identifiers and model symbols when interpreting these artifacts.

## Environment and installation

The manuscript reports the following experiment environment:

- Microsoft Windows 11, 64-bit.
- Python **3.14.0**.
- ANTLR **4.13.2** for parser generation.
- nuXmv **2.1.0**, using default batch mode.

`requirements.txt` contains the Python runtime dependency, `antlr4-python3-runtime==4.13.2`. The other imports in the supplied implementation use Python's standard library or repository-local modules. The tests use `unittest`; `pytest` is not required.

Run commands from the repository root. A virtual environment is optional:

```console
python -m venv .venv
```

Activate it on Windows Command Prompt:

```bat
.venv\Scripts\activate.bat
```

Or on Linux/macOS:

```sh
source .venv/bin/activate
```

Then install the dependency:

```console
python -m pip install -r requirements.txt
```

The ANTLR runtime must match the version used to generate `CDLexer.py` and `CDParser.py`; their headers and `checkVersion(...)` calls identify that version. The pin above follows the manuscript's ANTLR version. If replacing the generated parser, update the runtime pin accordingly. Parser regeneration and a Java installation are not required to run the included generated files.

Install [nuXmv](https://nuxmv.fbk.eu/) separately and make its executable available on `PATH`, or invoke it using its installed path. nuXmv is not installed by `pip`. An X-language simulation environment is needed only to rerun native simulation; it is not needed to process the saved nuXmv logs.

## 1. Convert CNL requirements into CTL/LTL

Run:

```console
python REQ2CTLLTL.py
```

The default configuration near the top of the script is:

```python
SCRIPT_DIR = Path(__file__).resolve().parent
REQUIREMENTS_FILE = SCRIPT_DIR / "FMCS/FMCS_Req_Final.md"
TRACE_FILE = SCRIPT_DIR / "FMCS/FMCS_Req_TC_validated.txt"
X_MODEL_FILE = SCRIPT_DIR / "FMCS/input_XModel_FMCS.txt"
OUTPUT_FILE = SCRIPT_DIR / "FMCS/FMCS_CTL_and_LTL_Specifications.smv"
STRICT_MODE = True
PAUSE_AFTER_RUN = True
```

| Input | Role |
| --- | --- |
| `FMCS_Req_Final.md` | Structured Chinese CNL requirements with requirement identifiers. |
| `FMCS_Req_TC_validated.txt` | Existing `source(...)`, `state_source(...)`, `condition_source(...)`, `event_source(...)`, and `value_source(...)` mappings. |
| `input_XModel_FMCS.txt` | X model used to validate instances, states, ports, variables, types, and value domains. |

For another case, change these four path settings to its inputs and output. This script does not provide command-line path arguments. Preserve the supported CNL templates and trace-file syntax; arbitrary prose or a direct English translation of a template is not automatically accepted by the Chinese parser.

With `STRICT_MODE = True`, a failed requirement conversion rejects the run without writing partial results. A failed run does not replace an existing output file. `PAUSE_AFTER_RUN = True` waits for Enter after execution; set it to `False` for unattended terminal use.

The output contains annotated specifications with requirement identifiers, original text, pattern and logic types, semantic warnings where applicable, and auxiliary trigger-reachability checks. For the supplied FMCS inputs, the regression test expects:

| Quantity | Expected value |
| --- | --- |
| Formal requirement specifications | 51 |
| CTL specifications | 2 |
| LTL specifications | 49 |
| Auxiliary trigger-reachability checks | 41 |

The auxiliary properties have names beginning with `COV_` and check `EF(P)` for explicit triggering conditions. They are counted separately from the 51 formal specifications.

**The output is a specification catalog, not a standalone system model.** It also repeats the property statements in a final copy block, delimited by Chinese `BEGIN` and `END` comment markers. When assembling a verification model, copy **only that final block once**. Do not append the entire catalog: that would duplicate formal properties and named coverage checks. Keep the annotated catalog for provenance matching during traceability.

To preserve the distributed catalog while experimenting, change `OUTPUT_FILE` to a new filename before running the converter.

## 2. Transform an X model into a nuXmv model

`main.py` reads an X model, parses it, constructs the intermediate representation, and writes the generated nuXmv model. It does not run requirement formalization, invoke nuXmv, or produce the traceability report.

The currently active paths inside `main()` select the event-semantics example:

```python
input_file = "EventSemanticsTests/input_XModel_EventSemantics.txt"
output_file = "EventSemanticsTests/input_XModel_EventSemantics_Result.smv"
```

Run from the repository root:

```console
python main.py
```

For the FMCS baseline, replace those two active assignments with:

```python
input_file = "FMCS/input_XModel_FMCS.txt"
output_file = "FMCS/input_XModel_FMCS_Regenerated.smv"
```

For FI-01, use:

```python
input_file = "TestWrong/input_FMCS_FI-01.txt"
output_file = "TestWrong/input_FMCS_FI_01_Regenerated.smv"
```

Apply the same naming convention for FI-02–FI-05. The source filenames use `FI-01`, whereas the saved verification filenames use `FI_01`.

Only one input/output pair should be active. The output directory must already exist. Generation replaces the selected output file; the examples above use new filenames to retain saved experimental models. Check the console completion message and generated file: the current entry point prints caught errors without explicitly returning a nonzero exit status.

For a transformation-consistency input, configure `input_file` with the X source `.txt` in `TransformationConsistencyTests/` and choose a new output `.smv` in that directory. The CNL and trace inputs in that directory can similarly be selected in `REQ2CTLLTL.py`. The event-semantics and transformation-consistency directories contain model-checking experiments; the two root `test_*.py` files are separate Python regression suites.

## 3. Run nuXmv model checking

There are two ways to use the artifacts:

- **Recheck a saved verification model:** run nuXmv on the supplied `.smv` containing the model and its intended properties.
- **Verify a newly generated model:** copy the regenerated model to a new verification `.smv`, then append the relevant property block once in the `MODULE main` context. `main.py` generates model code only; it does not automatically merge the requirement catalog into the model. For transformation tests, retain their intended test properties when rebuilding the model.

For example, to recheck the saved FMCS baseline in default batch mode:

```console
nuXmv FMCS/input_XModel_FMCS_Result.smv > FMCS/FMCS_baseline_rechecked.txt 2>&1
```

To recheck FI-01:

```console
nuXmv TestWrong/input_FMCS_FI_01_Result.smv > TestWrong/input_FMCS_FI_01_Rechecked.txt 2>&1
```

To recheck the saved event-semantics model:

```console
nuXmv EventSemanticsTests/input_XModel_EventSemantics_Result.smv > EventSemanticsTests/EventSemantics_rechecked.txt 2>&1
```

Use the corresponding `.smv` in `TransformationConsistencyTests/` for its model-checking experiment. On Windows, if nuXmv is not on `PATH`, replace `nuXmv` with its executable path; PowerShell requires `&` before a quoted executable path.

Check that the model contains the intended properties before running it, and inspect the log for parse errors, verdicts, and counterexamples. The expected FMCS baseline has 51 true formal-property verdicts and 41 true auxiliary reachability verdicts. FI-01–FI-05 contain violated formal specifications; false `COV_` verdicts are auxiliary warnings and are summarized separately.

For numerical reproduction of the published compression counts, use the saved raw logs. Rerunning a different nuXmv version or configuration can produce different valid counterexample traces and therefore different trace lengths.

## 4. Reduce counterexamples and generate traceability reports

`reduce_and_trace.py` consumes an existing nuXmv log, its verification model, and an annotated requirement-specification catalog. It does not rerun model checking.

Run it without arguments to process the current default **FI-05** files:

```console
python reduce_and_trace.py
```

The defaults are `TestWrong/input_FMCS_FI_05_Result.txt`, the matching `.smv`, and `TestWrong/FMCS_CTL_and_LTL_Specifications.smv`. Its default outputs are the input log's filename with `_compressed.txt` and `_Trace_diagnosis.txt` suffixes; existing files at those paths are replaced.

To process the saved FI-01 log without overwriting its distributed reports, use:

```console
python reduce_and_trace.py TestWrong/input_FMCS_FI_01_Result.txt --model TestWrong/input_FMCS_FI_01_Result.smv --requirements FMCS/FMCS_CTL_and_LTL_Specifications.smv --compressed-output outputs/FI_01_compressed.txt --report-output outputs/FI_01_Trace_diagnosis.txt
```

The script creates the output directories as needed. To process newly rechecked results, change the log argument to `TestWrong/input_FMCS_FI_01_Rechecked.txt`, keeping the model and catalog aligned with that run.

For the saved baseline:

```console
python reduce_and_trace.py FMCS/input_XModel_FMCS_Result.txt --model FMCS/input_XModel_FMCS_Result.smv --requirements FMCS/FMCS_CTL_and_LTL_Specifications.smv --compressed-output outputs/FMCS_baseline_compressed.txt --report-output outputs/FMCS_baseline_Trace_diagnosis.txt
```

The report includes a coverage summary even when no formal-property counterexample is present. When violations exist, it presents originating requirements, relevant instances and model symbols, retained evidence, violation categories, and compression statistics. Use the annotated catalog corresponding to the checked properties; a model with property statements alone does not replace the catalog's source metadata.

CLI help is available through:

```console
python reduce_and_trace.py --help
```

The default `--minimum-run` is 3. Keep the default reduction settings when comparing with the saved regression results.

## 5. Run the Python regression tests

### Requirement formalization

```console
python -m unittest -v test_requirement_formalization
```

Or run the file directly:

```console
python test_requirement_formalization.py
```

These eight tests require the ANTLR runtime, generated parser files, and the three FMCS input files used by `REQ2CTLLTL.py`. They check specification counts and a formula digest, target-symbol existence, zero-step response semantics, and rejection of unsupported response wording, invalid states, wrong event directions, and invalid numeric values. They generate model text in memory and do not invoke the nuXmv executable.

### Counterexample reduction and traceability

```console
python -m unittest -v test_reduce_and_trace
```

Or:

```console
python test_reduce_and_trace.py
```

The suite contains nine self-contained tests and three FMCS integration tests. The independent tests cover violation classification, multiple matching sources, UTF-16 log reading, coverage separation, and incomplete coverage reporting. The integration tests read all five saved FI model/log pairs and a matching annotated specification catalog. They check provenance counts, instance mappings, violated requirement identifiers, and compression statistics without invoking nuXmv.

The integration tests automatically locate the files in `TestWrong/` and search for the catalog in `TestWrong/` or `FMCS/`, among other supported locations. If the fixtures are absent, those three tests are **skipped**; `OK (skipped=3)` does not mean that the FMCS integration results were verified.

For a different fixture location, set `FMCS_TRACE_TEST_DATA` to the folder containing all five model/log pairs and `FMCS_TRACE_REQUIREMENTS` to the catalog file. For example, in Windows PowerShell:

```powershell
$env:FMCS_TRACE_TEST_DATA = (Resolve-Path "TestWrong").Path
$env:FMCS_TRACE_REQUIREMENTS = (Resolve-Path "FMCS/FMCS_CTL_and_LTL_Specifications.smv").Path
python -m unittest -v test_reduce_and_trace
```

The expected saved-log compression totals encoded in the regression suite are:

| Case | Counterexamples | Raw state blocks | Retained | Folded |
| --- | --- | --- | --- | --- |
| FI-01 | 3 | 636 | 132 | 504 |
| FI-02 | 1 | 212 | 44 | 168 |
| FI-03 | 1 | 191 | 24 | 167 |
| FI-04 | 2 | 424 | 96 | 328 |
| FI-05 | 5 | 1055 | 215 | 840 |
| Total | 12 | 2518 | 511 | 2007 |

The total reduction rate is 79.71%. These are stored regression expectations; a new verification run is checked against its own raw output and should not be described as reproducing those counts unless it does so.

Run both suites together using:

```console
python -m unittest -v test_requirement_formalization test_reduce_and_trace
```

## Paths and common issues

| Issue | Action |
| --- | --- |
| `ModuleNotFoundError: antlr4` | Install `requirements.txt` using the same Python interpreter that runs the scripts. |
| ANTLR version mismatch | Match the runtime to the generated lexer/parser version. |
| Missing `CDLexer`, `CDParser`, or `CDVisitor` | Keep the generated files in the repository root with their canonical filenames. |
| `main.py` cannot find an input | Run from the repository root, or change `input_file` and `output_file` to valid paths. |
| The wrong case is generated | Change the active pair inside `main()`; its default is the event-semantics example. |
| The converter waits after completion | Press Enter, or set `PAUSE_AFTER_RUN = False`. |
| Duplicate properties or duplicate `COV_` names | Append the final property copy block once, rather than the whole specification catalog. |
| FI tests are skipped | Ensure all ten FI model/log fixtures and the annotated catalog are present, or set the test environment variables. |
| A trace report lacks requirement source matches | Use the catalog corresponding to the checked model and log, preserving its metadata comments. |

`REQ2CTLLTL.py` and the traceability defaults derive paths from the script location. `main.py` uses paths relative to the working directory. A full path computed with `Path(__file__).resolve()` is portable; it is different from a hard-coded path to another user's drive. Local absolute paths may be used, but must be changed when moving the project.

## References

- [ANTLR Python target documentation](https://github.com/antlr/antlr4/blob/dev/doc/python-target.md).
- [nuXmv downloads](https://nuxmv.fbk.eu/download.html) and [user manual](https://nuxmv.fbk.eu/downloads/nuxmv-user-manual.pdf).

The manuscript provides the method, supported model subset, evaluation design, and interpretation of the results. This repository documents the implementation and the experimental artifacts used to inspect and reproduce that workflow.
