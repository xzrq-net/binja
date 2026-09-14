"""Close through the managed queue and GUI, including the file's other views."""
result = bridge.execution.close(request, args["force"])
discarded = "; unsaved changes discarded" if result["discarded"] else ""
print(f"Closed {result['path']}  {len(result['handles'])} views{discarded}")
