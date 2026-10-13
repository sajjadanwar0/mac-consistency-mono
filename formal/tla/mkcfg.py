import sys
g1,g2,g3,g6,inv=sys.argv[1:6]
print(f"""SPECIFICATION GSpec
SYMMETRY Perms
INVARIANT {inv}
CONSTANTS
    Agents = {{a1, a2}}
    Cells = {{c1, c2}}
    Values = {{v1}}
    Tools = {{t1}}
    NULL = "NULL"
    MaxOps = 2
    ExternalCells = {{}}
CONSTANT AllowSkew = FALSE
CONSTANT G1 = {g1}
CONSTANT G2 = {g2}
CONSTANT G3 = {g3}
CONSTANT G6 = {g6}""")
