from zimpy import WikiServer
import pathlib
import glob


w = list(pathlib.Path("/Users/tony/zim/").glob("*.zim"))
print('The following ZIM files were found:')
for i in range(len(w)):
    print(f' {i+1}) {w[i].name.replace(".zim", "")}')

print('')
idx = int(input('> '))-1

assert idx >= 0 and idx < len(w)
WikiServer(w[idx])
