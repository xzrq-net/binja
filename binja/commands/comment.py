"""Function comments at a function start; view comments at other addresses."""
from binja.analysis import function_info, named_function, one_function, resolve_address
from binja.editing import edit_result

function = named_function(bv, args["function"])
address = function.start if function else resolve_address(bv, args["function"])
if function is None:
    function = one_function(bv.get_functions_at(address), args["function"])
before = function.comment if function else bv.get_comment_at(address)
if before != args["text"]:
    if function:
        function.comment = args["text"]
    else:
        bv.set_comment_at(address, args["text"])
bv.update_analysis_and_wait()
after = function.comment if function else bv.get_comment_at(address)
scope = "function" if function else "address"
result = edit_result(request, before != after, address=hex(address), scope=scope,
    function=function_info(function) if function else None, before=before, after=after)
print(f"{scope} comment @ {address:#x}")
