"""Native IL lines, including source addresses and IL instruction indexes."""
from binja.analysis import function_listing, require_il_view, resolve_function

require_il_view(bv)
function = resolve_function(bv, args["function"])
result = function_listing(request, function, args["view"], args["offset"], args["limit"], args["ssa"])
