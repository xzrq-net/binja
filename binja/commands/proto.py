"""Apply a function type without changing the function's symbol name."""
from binja.analysis import function_info, resolve_function
from binja.common import Error
from binja.editing import edit_result, parse_type

function = resolve_function(bv, args["function"])
prototype = parse_type(bv, args["prototype"])
if prototype.type_class != bn.TypeClass.FunctionTypeClass:
    raise Error(f"Prototype must be a function type, got {prototype}.")
before = str(function.type)
if before != str(prototype):
    function.set_user_type(prototype)
bv.update_analysis_and_wait()
after = str(function.type)
result = edit_result(request, before != after, function=function_info(function), before=before, after=after)
