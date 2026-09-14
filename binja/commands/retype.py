"""Retype a native variable and reacquire it by identifier after analysis."""
from binja.analysis import function_info, resolve_function
from binja.common import Error
from binja.editing import edit_result, parse_type, resolve_variable, type_text, variable_info

function = resolve_function(bv, args["function"])
variable = resolve_variable(function, args["variable"])
identifier = variable.identifier
new_type = parse_type(bv, args["type"])
before = type_text(variable.type)
if before != str(new_type):
    variable.set_type_async(new_type)
bv.update_analysis_and_wait()
variable = next((v for v in function.vars if v.identifier == identifier), None)
if variable is None:
    raise Error(f"Variable id:{identifier:#x} disappeared after analysis; the edit remains applied. Inspect IL or undo.")
after = type_text(variable.type)
result = edit_result(request, before != after, function=function_info(function),
    variable=variable_info(variable), before=before, after=after)
print(f"{variable.name}  id:{identifier:#x}  {variable.source_type.name}/{variable.index}/{variable.storage}")
