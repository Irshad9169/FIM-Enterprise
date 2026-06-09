import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchUsers, deleteUser, createUser, updateUser } from "../api/dashboard";
import { Trash2, UserPlus, CheckCircle, XCircle, Edit2, Shield, Key } from "lucide-react";

export default function UsersPage() {
  const queryClient = useQueryClient();
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<any>(null);
  
  const [newUser, setNewUser] = useState({ username: "", email: "", password: "", role: "viewer" });
  const [editForm, setEditForm] = useState({ role: "", password: "" });
  const [toast, setToast] = useState<{msg: string; ok: boolean} | null>(null);
  useEffect(() => {
    if (toast) { const t = setTimeout(() => setToast(null), 4000); return () => clearTimeout(t); }
  }, [toast]);

  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: fetchUsers,
  });

  const createMutation = useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      setShowAddModal(false);
      setNewUser({ username: "", email: "", password: "", role: "viewer" });
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err: any) => alert(err.message || "Failed to create user"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: any }) => updateUser(userId, data),
    onSuccess: () => {
      setShowEditModal(false);
      setSelectedUser(null);
      setEditForm({ role: "", password: "" });
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err: any) => alert(err.message || "Failed to update user"),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setToast({ msg: "User deactivated successfully", ok: true });
    },
    onError: (e: any) => setToast({ msg: e.message || "Failed to delete user", ok: false }),
  });

  const handleEditClick = (user: any) => {
    setSelectedUser(user);
    setEditForm({ role: user.role, password: "" });
    setShowEditModal(true);
  };

  const handleUpdate = () => {
    const data: any = { role: editForm.role };
    if (editForm.password) data.password = editForm.password;
    updateMutation.mutate({ userId: selectedUser.id, data });
  };

  if (isLoading) return <div className="text-center py-12 text-slate-400">Loading users...</div>;

  return (
    <div className="space-y-6">
      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg border text-sm shadow-lg ${
          toast.ok ? "bg-green-900/90 border-green-700 text-green-200" : "bg-red-900/90 border-red-700 text-red-200"
        }`}>
          {toast.ok ? "✅" : "❌"} {toast.msg}
        </div>
      )}
      <div className="flex justify-between items-center bg-slate-900 p-4 rounded-lg border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white">User Management</h1>
          <p className="text-slate-400 text-sm">Manage system access and roles</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center gap-2"
        >
          <UserPlus size={16} /> Add User
        </button>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left text-slate-300">
          <thead className="bg-slate-950/50 text-slate-400 font-semibold uppercase text-xs border-b border-slate-800">
            <tr>
              <th className="px-6 py-4">User</th>
              <th className="px-6 py-4">Role</th>
              <th className="px-6 py-4">Status</th>
              <th className="px-6 py-4">Created</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {users?.map((user: any) => (
              <tr key={user.id} className="hover:bg-slate-800/50">
                <td className="px-6 py-4">
                  <div className="font-medium text-white">{user.username}</div>
                  <div className="text-xs text-slate-500">{user.email}</div>
                </td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-1 rounded text-xs border uppercase ${
                    user.role === 'admin' ? 'bg-purple-900/30 text-purple-400 border-purple-800' : 'bg-slate-800 text-slate-300 border-slate-700'
                  }`}>
                    {user.role}
                  </span>
                </td>
                <td className="px-6 py-4">
                  {user.is_active ? (
                    <span className="flex items-center gap-1 text-green-400 text-xs">
                      <CheckCircle size={12} /> Active
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-red-400 text-xs">
                      <XCircle size={12} /> Inactive
                    </span>
                  )}
                </td>
                <td className="px-6 py-4 text-slate-500">
                  {new Date(user.created_at).toLocaleDateString()}
                </td>
                <td className="px-6 py-4 text-right">
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => handleEditClick(user)}
                      className="p-2 text-blue-400 hover:bg-blue-900/20 rounded"
                      title="Edit User"
                    >
                      <Edit2 size={16} />
                    </button>
                    
                    {/* Disable delete for admin users */}
                    {user.role !== 'admin' && (
                      <button
                        onClick={() => {
                          if(confirm('Delete user?')) deleteMutation.mutate(user.id);
                        }}
                        className="p-2 text-red-400 hover:bg-red-900/20 rounded"
                        title="Delete User"
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Add User Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 w-96 shadow-xl">
            <h2 className="text-lg font-bold text-white mb-4">Add New User</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Username</label>
                <input
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newUser.username}
                  onChange={e => setNewUser({...newUser, username: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Email</label>
                <input
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newUser.email}
                  onChange={e => setNewUser({...newUser, email: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Password</label>
                <input
                  type="password"
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newUser.password}
                  onChange={e => setNewUser({...newUser, password: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Role</label>
                <select
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newUser.role}
                  onChange={e => setNewUser({...newUser, role: e.target.value})}
                >
                  <option value="viewer">Viewer</option>
                  <option value="trainee">Trainee</option>
                  <option value="analyst">Analyst</option>
                  <option value="auditor">Auditor</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div className="flex justify-end gap-2 mt-6">
                <button
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 text-slate-300 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={() => createMutation.mutate(newUser)}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  Create User
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit User Modal */}
      {showEditModal && selectedUser && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 w-96 shadow-xl">
            <h2 className="text-lg font-bold text-white mb-1">Edit User</h2>
            <p className="text-sm text-slate-400 mb-4">{selectedUser.username}</p>
            
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
                  <Shield size={12} /> Role
                </label>
                <select
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={editForm.role}
                  onChange={e => setEditForm({...editForm, role: e.target.value})}
                >
                  <option value="viewer">Viewer</option>
                  <option value="trainee">Trainee</option>
                  <option value="analyst">Analyst</option>
                  <option value="auditor">Auditor</option>
                  <option value="admin">Admin</option>
                </select>
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
                  <Key size={12} /> Reset Password (Optional)
                </label>
                <input
                  type="password"
                  placeholder="New password..."
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={editForm.password}
                  onChange={e => setEditForm({...editForm, password: e.target.value})}
                />
              </div>

              <div className="flex justify-end gap-2 mt-6">
                <button
                  onClick={() => setShowEditModal(false)}
                  className="px-4 py-2 text-slate-300 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={handleUpdate}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  Save Changes
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
