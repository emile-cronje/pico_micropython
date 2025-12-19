from btree import BTree

# Example usage:
bt = BTree(3, 'btree_data.json')  # Create a B-tree with a minimum degree of 3 and specify a storage file

# Insert key-value pairs
key_value_pairs = [(3, 'A'), (8, 'B'), (1, 'C'), (4, 'D'), (7, 'E'), (2, 'F'), (5, 'G'), (6, 'H')]
dict = {}

for key, value in key_value_pairs:
    bt.insert(key, value)
    dict[key] = value    

# Search for a key and retrieve the associated value
print(bt.search(5))  # 'G'
print(bt.search(9))  # None (key not found)

print(dict[6])  # 'G'
print(7 in dict.keys())