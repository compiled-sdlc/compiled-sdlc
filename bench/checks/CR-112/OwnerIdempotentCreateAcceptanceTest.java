package org.springframework.samples.petclinic.customers.web;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.customers.model.Owner;
import org.springframework.samples.petclinic.customers.model.OwnerRepository;
import org.springframework.samples.petclinic.customers.web.mapper.OwnerEntityMapper;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-112: a create carrying an Idempotency-Key happens once.
 *
 * The mapper is stubbed to do what the real one does, so an implementation that
 * still maps through it and one that does not are both answered the same way.
 *
 * Passability: Keep a map on the resource from key to the request and its answer. The
 * fixture replays the same header twice and then a different body under the same key,
 * all through MockMvc, and counts saves on the mocked repository.
 * Confirmed empirically: 11 of 12 cells passed it in the full run.
 */
@WebMvcTest(OwnerResource.class)
@ActiveProfiles("test")
class OwnerIdempotentCreateAcceptanceTest {

    private static final String KEY = "Idempotency-Key";

    @Autowired
    MockMvc mvc;

    @MockitoBean
    OwnerRepository ownerRepository;

    @MockitoBean
    OwnerEntityMapper ownerEntityMapper;

    private String body(String firstName) {
        return "{\"firstName\":\"" + firstName + "\",\"lastName\":\"Franklin\","
            + "\"address\":\"110 W. Liberty St.\",\"city\":\"Madison\","
            + "\"telephone\":\"6085551023\"}";
    }

    private void givenTheRepositoryAnswers() {
        given(ownerEntityMapper.map(any(Owner.class), any(OwnerRequest.class)))
            .willAnswer(invocation -> {
                Owner owner = invocation.getArgument(0);
                OwnerRequest request = invocation.getArgument(1);
                owner.setFirstName(request.firstName());
                owner.setLastName(request.lastName());
                owner.setAddress(request.address());
                owner.setCity(request.city());
                owner.setTelephone(request.telephone());
                return owner;
            });
        given(ownerRepository.save(any(Owner.class)))
            .willAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void shouldCreateTheFirstRequestUnderAKey() throws Exception {
        givenTheRepositoryAnswers();

        mvc.perform(post("/owners")
                .header(KEY, "key-first")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("George")))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.firstName").value("George"));

        verify(ownerRepository, times(1)).save(any(Owner.class));
    }

    @Test
    void shouldAnswerARepeatWithTheOwnerItAlreadyCreated() throws Exception {
        givenTheRepositoryAnswers();

        mvc.perform(post("/owners")
                .header(KEY, "key-repeat")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("George")))
            .andExpect(status().isCreated());

        mvc.perform(post("/owners")
                .header(KEY, "key-repeat")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("George")))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.firstName").value("George"))
            .andExpect(jsonPath("$.lastName").value("Franklin"));

        verify(ownerRepository, times(1)).save(any(Owner.class));
    }

    @Test
    void shouldRefuseADifferentBodyUnderAKeyAlreadyUsed() throws Exception {
        givenTheRepositoryAnswers();

        mvc.perform(post("/owners")
                .header(KEY, "key-conflict")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("George")))
            .andExpect(status().isCreated());

        mvc.perform(post("/owners")
                .header(KEY, "key-conflict")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("Betty")))
            .andExpect(status().isConflict());

        verify(ownerRepository, times(1)).save(any(Owner.class));
    }

    @Test
    void shouldCreateAgainUnderAKeyNotYetUsed() throws Exception {
        givenTheRepositoryAnswers();

        mvc.perform(post("/owners")
                .header(KEY, "key-one")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("George")))
            .andExpect(status().isCreated());

        mvc.perform(post("/owners")
                .header(KEY, "key-two")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("George")))
            .andExpect(status().isCreated());

        verify(ownerRepository, times(2)).save(any(Owner.class));
    }

    @Test
    void shouldBeUnchangedWhenNoKeyIsSent() throws Exception {
        givenTheRepositoryAnswers();

        mvc.perform(post("/owners")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("George")))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.firstName").value("George"));

        mvc.perform(post("/owners")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body("George")))
            .andExpect(status().isCreated());

        verify(ownerRepository, times(2)).save(any(Owner.class));
        verify(ownerRepository, never()).findAll();
    }
}
