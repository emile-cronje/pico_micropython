from btree_custom_crud import BTree

# Example Usage:
btree = BTree(t=2, filename="btree_file.pickle")

# Inserting keys into the B-tree
keys_to_insert = [3, 7, 1, 5, 12, 8, 15, 2, 10, 6]
values_to_insert = ["apple", "banana", "cherry", "date", "elderberry", "fig", "grape", "kiwi", "lemon", "mango"]
for key, value in zip(keys_to_insert, values_to_insert):
    btree.insert(key, value)
    btree.periodic_save()  # Save periodically

# Updating the value of a node with a specific key
btree.update_value(5, "new_value_for_5")
btree.update_value(12, "new_value_for_12")
btree.periodic_save()  # Save after update

# Deleting a key from the B-tree
btree.delete(2)
btree.periodic_save()  # Save after deletion

# After all modifications, save the final state
btree.save_to_file()

# Loading B-tree from the file
new_btree = BTree(t=2, filename="btree_file.pickle")
new_btree.load_from_file()

# Searching again after loading
keys_to_search = [5, 8, 2, 11]
for key in keys_to_search:
    if new_btree.search(key):
        print(f"Key {key} found in the loaded B-tree with value: {new_btree.search(key)}")
    else:
        print(f"Key {key} not found in the loaded B-tree")

print("Count: " + str(new_btree.count_all()))
value_5 = new_btree.get_value(5)
value_12 = new_btree.get_value(12)
print("Item 5: " + str(value_5))
print("Item 12: " + str(value_12))