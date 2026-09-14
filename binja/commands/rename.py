"""Rename one resolved function and read its native name back after analysis."""
from binja.analysis import function_info, resolve_function
from binja.editing import edit_result

function = resolve_function(bv, args["function"])
before = function.name
if before != args["name"]:
    function.name = args["name"]
bv.update_analysis_and_wait()
after = function.name
result = edit_result(request, before != after, function=function_info(function), before=before, after=after)
