import json as ujson

class BTreeNode:
    def __init__(self, is_leaf=True):
        self.is_leaf = is_leaf
        self.keys = []
        self.values = []
        self.children = []

class BTree:
    def __init__(self, t, filename):
        self.root = BTreeNode()
        self.t = t  # Minimum degree
        self.filename = filename

    def insert(self, key, value):
        root = self.root
        
        if len(root.keys) == (2 * self.t) - 1:
            new_root = BTreeNode(is_leaf=False)
            new_root.children.append(self.root)
            self.split_child(new_root, 0)
            self.root = new_root
            self.insert_non_full(new_root, key, value)
        else:
            self.insert_non_full(root, key, value)
            
        self.periodic_save()            

    def insert_non_full(self, x, key, value):
        i = len(x.keys) - 1

        if x.is_leaf:
            x.keys.append(None)
            x.values.append(None)

            while i >= 0 and key < x.keys[i]:
                x.keys[i + 1] = x.keys[i]
                x.values[i + 1] = x.values[i]
                i -= 1

            x.keys[i + 1] = key
            x.values[i + 1] = value
        else:
            while i >= 0 and key < x.keys[i]:
                i -= 1

            i += 1

            if len(x.children[i].keys) == (2 * self.t) - 1:
                self.split_child(x, i)

                if key > x.keys[i]:
                    i += 1

            self.insert_non_full(x.children[i], key, value)

    def split_child(self, x, i):
        t = self.t
        y = x.children[i]
        z = BTreeNode(is_leaf=y.is_leaf)

        x.children.insert(i + 1, z)
        x.keys.insert(i, y.keys[t - 1])
        x.values.insert(i, y.values[t - 1])

        z.keys = y.keys[t:]
        z.values = y.values[t:]
        y.keys = y.keys[:t - 1]
        y.values = y.values[:t - 1]

        if not y.is_leaf:
            z.children = y.children[t:]
            y.children = y.children[:t]

    def update_value(self, key, new_value):
        node, index = self.search_node(self.root, key)
        if node is not None and index is not None:
            node.values[index] = new_value
            self.periodic_save()

    def search_node(self, node, key):
        i = 0
        while i < len(node.keys) and key > node.keys[i]:
            i += 1

        if i < len(node.keys) and key == node.keys[i]:
            return node, i
        elif node.is_leaf:
            return None, None
        else:
            return self.search_node(node.children[i], key)

    def search(self, key):
        node, index = self.search_node(self.root, key)
        return node is not None and index is not None

    def delete(self, key):
        root = self.root
        self.delete_recursive(root, key)

        if len(root.keys) == 0 and len(root.children) > 0:
            self.root = root.children[0]

    def delete_recursive(self, x, key):
        i = 0

        while i < len(x.keys) and key > x.keys[i]:
            i += 1

        if i < len(x.keys) and key == x.keys[i]:
            if x.is_leaf:
                x.keys.pop(i)
                x.values.pop(i)
            else:
                child = x.children[i]
                if len(child.keys) >= self.t:
                    x.keys[i], x.values[i] = self.get_predecessor(child)
                    self.delete_recursive(child, x.keys[i])
                else:
                    right_sibling = x.children[i + 1]
                    if len(right_sibling.keys) >= self.t:
                        x.keys[i], x.values[i] = self.get_successor(right_sibling)
                        self.delete_recursive(right_sibling, x.keys[i])
                    else:
                        self.merge(x, i)
                        self.delete_recursive(child, key)
        else:
            if x.is_leaf:
                return
            
            child = x.children[i]

            if len(child.keys) == self.t - 1:
                self.fill(child, i)

            if i > len(x.keys):
                i -= 1

            self.delete_recursive(x.children[i], key)

    def fill(self, x, i):
        if i > 0 and len(x.children[i - 1].keys) >= self.t:
            self.borrow_from_prev(x, i)
        elif i < len(x.keys) and len(x.children[i + 1].keys) >= self.t:
            self.borrow_from_next(x, i)
        elif i > 0:
            self.merge(x, i - 1)
        else:
            self.merge(x, i)

    def borrow_from_prev(self, x, i):
        child = x.children[i]
        prev_sibling = x.children[i - 1]

        child.keys.insert(0, x.keys[i - 1])
        child.values.insert(0, x.values[i - 1])

        if not child.is_leaf:
            child.children.insert(0, prev_sibling.children.pop())

        x.keys[i - 1] = prev_sibling.keys.pop()
        x.values[i - 1] = prev_sibling.values.pop()

    def borrow_from_next(self, x, i):
        child = x.children[i]
        next_sibling = x.children[i + 1]

        child.keys.append(x.keys[i])
        child.values.append(x.values[i])

        if not child.is_leaf:
            child.children.append(next_sibling.children.pop(0))

        x.keys[i] = next_sibling.keys.pop(0)
        x.values[i] = next_sibling.values.pop(0)

    def merge(self, x, i):
        child = x.children[i]
        next_sibling = x.children[i + 1]

        child.keys.append(x.keys.pop(i))
        child.values.append(x.values.pop(i))
        child.keys.extend(next_sibling.keys)
        child.values.extend(next_sibling.values)

        if not child.is_leaf:
            child.children.extend(next_sibling.children)

        x.children.pop(i + 1)

    def get_predecessor(self, x):
        if x.is_leaf:
            return x.keys[-1], x.values[-1]
        
        return self.get_predecessor(x.children[-1])

    def get_successor(self, x):
        if x.is_leaf:
            return x.keys[0], x.values[0]
        
        return self.get_successor(x.children[0])

    def save_to_file(self):
        data = self.serialize(self.root)

        with open(self.filename, 'w') as f:
            ujson.dump(data, f)

    def load_from_file(self):
        try:
            with open(self.filename, 'r') as f:
                data = ujson.load(f)
                self.root = self.deserialize(data)
        except OSError:
            # File not found or other IO error, start with an empty tree
            self.root = BTreeNode(leaf=True)

    def periodic_save(self, threshold=10):
        # Save to file periodically
        # You can customize the threshold (number of insertions) before saving
        if len(self.root.keys) % threshold == 0:
            self.save_to_file()
            
    def serialize(self, node):
        if node is None:
            return None

        serialized_node = {
            'is_leaf': node.is_leaf,
            'keys': node.keys,
            'values': node.values,
            'children': []
        }

        for child in node.children:
            serialized_node['children'].append(self.serialize(child))

        return serialized_node

    def deserialize(self, serialized_node):
        if serialized_node is None:
            return None

        node = BTreeNode(is_leaf=serialized_node['is_leaf'])
        node.keys = serialized_node['keys']
        node.values = serialized_node['values']

        for child_data in serialized_node['children']:
            node.children.append(self.deserialize(child_data))

        return node
    
    def count(self, key):
            return self.count_recursive(self.root, key)

    def count_recursive(self, node, key):
        if node is None:
            return 0

        i = 0
        
        while i < len(node.keys) and key > node.keys[i]:
            i += 1

        if i < len(node.keys) and key == node.keys[i]:
            count = 1
        else:
            count = 0

        if not node.is_leaf:
            count += self.count_recursive(node.children[i], key)

        return count    

    def count_all(self):
        return self.count_all_recursive(self.root)

    def count_all_recursive(self, node):
        if node is None:
            return 0

        count = len(node.keys)

        if not node.is_leaf:
            for child in node.children:
                count += self.count_all_recursive(child)

        return count
    
    def get_value(self, key):
            node, index = self.search_node(self.root, key)
            return node.values[index] if node is not None and index is not None else None    

    def delete_all(self):
        self.root = BTreeNode()
        self.save_to_file()
