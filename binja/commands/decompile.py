"""The GUI's Pseudo C language representation, scoped to one function."""
from binja.analysis import function_listing, require_il_view, resolve_function

require_il_view(bv)
function = resolve_function(bv, args["function"])
result = function_listing(request, function, "pseudo-c", args["offset"], args["limit"])
