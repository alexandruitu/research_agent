const page = (title: string) => () => (
  <section>
    <h1>{title}</h1>
  </section>
);

export const UsersPage = page("Users");
